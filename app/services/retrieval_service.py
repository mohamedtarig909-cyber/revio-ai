"""
Retrieval Service — semantic case retrieval via pgvector.

Functions:
  embed_lead_context()    — build a rich text description of a lead, then embed it
  embed_text()            — embed arbitrary text
  retrieve_similar_cases() — cosine-similarity search in historical_cases
  build_context_for_planner() — assemble retrieved cases into an LLM-ready block
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.agents.tools import retrieve_similar_historical_cases

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536-dim, matches pgvector column
MAX_EMBEDDING_INPUT_CHARS = 8000


class RetrievalService:
    """
    Stateless service for embedding + retrieval.
    Inject into agents that need historical context.
    """

    def __init__(self, openai_api_key: str, db: AsyncSession) -> None:
        self._api_key = openai_api_key
        self._db = db
        self._client = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_lead_context(self, lead_data: dict[str, Any]) -> list[float]:
        """
        Build a descriptive text from lead_data and return its embedding.
        """
        text = self._lead_to_text(lead_data)
        return await self.embed_text(text)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        """
        Embed arbitrary text using OpenAI embeddings API.
        Truncates input to avoid token limit errors.
        """
        truncated = text[:MAX_EMBEDDING_INPUT_CHARS]
        response = await self._client.post(
            f"{OPENAI_API_BASE}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": EMBEDDING_MODEL,
                "input": truncated,
                "encoding_format": "float",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    async def retrieve_similar_cases(
        self,
        lead_data: dict[str, Any],
        industry: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Generate embedding for lead, then retrieve top-N similar cases.
        Falls back gracefully if embedding or pgvector fails.
        """
        try:
            embedding = await self.embed_lead_context(lead_data)
        except Exception as exc:
            logger.warning("Embedding failed; returning empty case list: %s", exc)
            return []

        try:
            cases = await retrieve_similar_historical_cases(
                db=self._db,
                embedding=embedding,
                industry=industry or lead_data.get("industry"),
                limit=limit,
            )
            logger.info("Retrieved %d similar historical cases", len(cases))
            return cases
        except Exception as exc:
            logger.warning("Case retrieval failed: %s", exc)
            return []

    def build_context_for_planner(
        self,
        cases: list[dict[str, Any]],
        max_cases: int = 10,
    ) -> str:
        """
        Format retrieved cases into a compact block for LLM prompt injection.
        """
        if not cases:
            return "No similar historical cases found."

        lines = [f"TOP {min(len(cases), max_cases)} SIMILAR HISTORICAL RECOVERIES:"]
        for i, case in enumerate(cases[:max_cases], 1):
            sim = case.get("similarity")
            sim_str = f" [{sim:.0%} similar]" if sim is not None else ""
            outcome = "✓ RECOVERED" if case.get("outcome_positive") else "✗ FAILED"
            strategy = case.get("winning_strategy") or {}
            channel = strategy.get("primary_channel") or case.get("channel_used", "?")
            discount = "yes" if strategy.get("discount_offered") else "no"
            human = "yes" if strategy.get("human_escalated") else "no"

            lines.append(
                f"\n{i}.{sim_str} {outcome}\n"
                f"   Summary: {case.get('case_summary', 'N/A')}\n"
                f"   Channel: {channel} | Discount: {discount} | Human: {human}"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _lead_to_text(lead_data: dict[str, Any]) -> str:
        """
        Convert lead_data dict to a rich natural-language description.
        This text becomes the query embedding for similarity search.
        """
        parts = []

        if industry := lead_data.get("industry"):
            parts.append(f"Industry: {industry}.")
        if company := lead_data.get("company"):
            parts.append(f"Company: {company}.")
        if deal_value := lead_data.get("deal_value"):
            parts.append(f"Deal value: ${deal_value:,.0f}.")
        if lead_type := lead_data.get("lead_type"):
            parts.append(f"Lead type: {lead_type}.")
        if days_dormant := lead_data.get("days_dormant"):
            parts.append(f"Days dormant: {days_dormant}.")
        if objections := lead_data.get("objections"):
            if isinstance(objections, list):
                parts.append(f"Objections raised: {', '.join(objections)}.")
            else:
                parts.append(f"Objections: {objections}.")
        if notes := lead_data.get("notes"):
            parts.append(f"CRM notes: {notes}.")
        if prev_attempts := lead_data.get("previous_attempts"):
            parts.append(f"Previous outreach attempts: {prev_attempts}.")
        if stage := lead_data.get("deal_stage"):
            parts.append(f"Deal stage: {stage}.")

        return " ".join(parts) if parts else "Lead with no additional context."

    async def close(self) -> None:
        await self._client.aclose()
