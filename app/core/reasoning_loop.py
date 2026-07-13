"""
Base iterative reasoning loop.

All new intelligence agents inherit from ReasoningAgent.
Implements the observe → reason → tool-call → re-reason → decide loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from app.config import get_settings

OPENAI_API_BASE = get_settings().openai_base_url.rstrip("/")
DEFAULT_MODEL = get_settings().llm_model
CONFIDENCE_THRESHOLD = 0.80
MAX_ITERATIONS = 5
ITERATION_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReasoningContext:
    """Mutable context passed through every reasoning iteration."""
    lead_data: dict[str, Any]
    crm_data: dict[str, Any] = field(default_factory=dict)
    memory_patterns: list[dict[str, Any]] = field(default_factory=list)
    retrieved_cases: list[dict[str, Any]] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    iteration_log: list[dict[str, Any]] = field(default_factory=list)
    current_confidence: float = 0.0
    tools_called: list[str] = field(default_factory=list)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class ReasoningResult:
    decision: dict[str, Any]
    confidence: float
    reasoning: str
    iterations: int
    tools_called: list[str]
    raw_responses: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ReasoningAgent(ABC):
    """
    Iterative reasoning loop base.

    Subclasses implement:
      - build_system_prompt()
      - build_user_prompt(context)
      - parse_response(raw) -> dict
      - get_tools() -> list[ToolDefinition]
      - is_decision_sufficient(decision) -> bool
    """

    def __init__(
        self,
        openai_api_key: str,
        model: str = DEFAULT_MODEL,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.api_key = openai_api_key
        self.model = model
        self.confidence_threshold = confidence_threshold
        self.max_iterations = max_iterations
        self._client = httpx.AsyncClient(timeout=60.0)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, context: ReasoningContext) -> ReasoningResult:
        """
        Execute the full iterative reasoning loop.
        """
        iteration = 0
        decision: dict[str, Any] = {}
        raw_responses: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1
            iteration_start = time.monotonic()

            logger.info(
                "Reasoning iteration %d/%d | confidence=%.2f",
                iteration,
                self.max_iterations,
                context.current_confidence,
            )

            # ---- Build messages ----
            messages = self._build_messages(context)

            # ---- Call LLM ----
            try:
                raw = await asyncio.wait_for(
                    self._call_llm(messages),
                    timeout=ITERATION_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning("LLM call timed out on iteration %d", iteration)
                break

            raw_responses.append(raw)

            # ---- Parse ----
            try:
                decision = self.parse_response(raw)
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Response parse error on iteration %d: %s", iteration, exc)
                context.iteration_log.append(
                    {"iteration": iteration, "error": str(exc), "raw": raw[:500]}
                )
                continue

            context.current_confidence = float(decision.get("confidence_score", 0.0))

            # ---- Log iteration ----
            elapsed = time.monotonic() - iteration_start
            context.iteration_log.append(
                {
                    "iteration": iteration,
                    "confidence": context.current_confidence,
                    "elapsed_ms": round(elapsed * 1000),
                    "tools_called_this_iter": [],
                }
            )

            # ---- Check confidence ----
            if self.is_decision_sufficient(decision):
                logger.info(
                    "Decision sufficient at iteration %d (confidence=%.2f)",
                    iteration,
                    context.current_confidence,
                )
                break

            # ---- Determine missing context and call tools ----
            missing = self._determine_missing_context(decision, context)
            if not missing:
                logger.info("No additional context available; accepting decision at iteration %d", iteration)
                break

            tools_called_this_iter: list[str] = []
            for tool_name, tool_args in missing.items():
                tool = self._get_tool(tool_name)
                if tool is None:
                    logger.warning("Tool %s not found; skipping", tool_name)
                    continue
                try:
                    result = await asyncio.wait_for(
                        tool.handler(**tool_args),
                        timeout=10.0,
                    )
                    context.tool_results[tool_name] = result
                    context.tools_called.append(tool_name)
                    tools_called_this_iter.append(tool_name)
                    logger.debug("Tool %s returned %s", tool_name, str(result)[:200])
                except Exception as exc:
                    logger.warning("Tool %s failed: %s", tool_name, exc)
                    context.tool_results[tool_name] = {"error": str(exc)}

            if context.iteration_log:
                context.iteration_log[-1]["tools_called_this_iter"] = tools_called_this_iter

        return ReasoningResult(
            decision=decision,
            confidence=context.current_confidence,
            reasoning=decision.get("reasoning", ""),
            iterations=iteration,
            tools_called=context.tools_called,
            raw_responses=raw_responses,
        )

    # ------------------------------------------------------------------
    # Abstract interface for subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    def build_system_prompt(self) -> str:
        ...

    @abstractmethod
    def build_user_prompt(self, context: ReasoningContext) -> str:
        ...

    @abstractmethod
    def parse_response(self, raw: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def get_tools(self) -> list[ToolDefinition]:
        ...

    def is_decision_sufficient(self, decision: dict[str, Any]) -> bool:
        """Override for custom sufficiency logic."""
        return decision.get("confidence_score", 0.0) >= self.confidence_threshold

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_messages(self, context: ReasoningContext) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt()}
        ]
        # Inject tool results from previous iterations as assistant/user turns
        for entry in context.iteration_log:
            if entry.get("tools_called_this_iter"):
                tool_summary = json.dumps(
                    {k: context.tool_results.get(k) for k in entry["tools_called_this_iter"]},
                    default=str,
                )
                messages.append(
                    {
                        "role": "user",
                        "content": f"Tool results from previous reasoning step:\n{tool_summary}",
                    }
                )
        messages.append({"role": "user", "content": self.build_user_prompt(context)})
        return messages

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _call_llm(self, messages: list[dict[str, Any]]) -> str:
        response = await self._client.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _determine_missing_context(
        self,
        decision: dict[str, Any],
        context: ReasoningContext,
    ) -> dict[str, dict[str, Any]]:
        """
        Inspect the decision for signals that more context is needed.
        Returns {tool_name: kwargs} for each tool that should be called.
        Subclasses can override for custom logic.
        """
        missing: dict[str, dict[str, Any]] = {}
        needs_history = decision.get("needs_campaign_history", False)
        needs_benchmarks = decision.get("needs_industry_benchmarks", False)
        needs_open_rates = decision.get("needs_open_rate_data", False)

        tool_map = {tool.name: tool for tool in self.get_tools()}
        lead_id = str(context.lead_data.get("id", ""))
        org_id = str(context.lead_data.get("organization_id", ""))
        industry = str(context.lead_data.get("industry", ""))

        if needs_history and "check_previous_campaign_performance" not in context.tools_called:
            if "check_previous_campaign_performance" in tool_map:
                missing["check_previous_campaign_performance"] = {
                    "lead_id": lead_id,
                    "organization_id": org_id,
                }

        if needs_benchmarks and "get_industry_benchmarks" not in context.tools_called:
            if "get_industry_benchmarks" in tool_map:
                missing["get_industry_benchmarks"] = {"industry": industry}

        if needs_open_rates and "check_customer_previous_open_rates" not in context.tools_called:
            if "check_customer_previous_open_rates" in tool_map:
                missing["check_customer_previous_open_rates"] = {
                    "lead_id": lead_id,
                    "organization_id": org_id,
                }

        return missing

    def _get_tool(self, name: str) -> ToolDefinition | None:
        return next((t for t in self.get_tools() if t.name == name), None)

    async def close(self) -> None:
        await self._client.aclose()
