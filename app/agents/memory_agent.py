"""
MEMORY AGENT — Persistent learning system.

Responsibilities:
  1. Store every campaign outcome (StrategyOutcome)
  2. Compute and refresh learned patterns (StrategyPattern)
  3. Expose patterns to PLANNER AGENT before strategy decisions
  4. Index cases into historical_cases for vector retrieval

Runs as a Celery task AND is callable directly from other agents.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import (
    HistoricalCase,
    PatternType,
    StrategyOutcome,
    StrategyPattern,
)
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MemoryAgent service class
# ---------------------------------------------------------------------------

class MemoryAgent:
    """
    Stateless service — each method receives a db session.
    Use from Celery tasks or directly from other services.
    """

    def __init__(
        self,
        openai_api_key: str,
        db: AsyncSession,
    ) -> None:
        self._api_key = openai_api_key
        self._db = db
        self._retrieval = RetrievalService(openai_api_key, db)

    # ------------------------------------------------------------------
    # 1. Store outcome
    # ------------------------------------------------------------------

    async def store_outcome(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        outcome: dict[str, Any],
        execution_plan_id: uuid.UUID | None = None,
    ) -> StrategyOutcome:
        """
        Persist a campaign outcome, then trigger pattern refresh and
        index the case for semantic retrieval.
        """
        record = StrategyOutcome(
            organization_id=organization_id,
            lead_id=lead_id,
            execution_plan_id=execution_plan_id,
            industry=outcome.get("industry"),
            lead_type=outcome.get("lead_type"),
            deal_value=outcome.get("deal_value"),
            objection_type=outcome.get("objection_type"),
            strategy_used=outcome.get("strategy_used"),
            channel_used=outcome.get("channel_used", "email"),
            sequence_used=outcome.get("sequence_used", []),
            discount_offered=bool(outcome.get("discount_offered", False)),
            human_escalated=bool(outcome.get("human_escalated", False)),
            response_received=bool(outcome.get("response_received", False)),
            deal_recovered=bool(outcome.get("deal_recovered", False)),
            revenue_closed=outcome.get("revenue_closed"),
            time_to_response_hours=outcome.get("time_to_response_hours"),
            total_messages_sent=int(outcome.get("total_messages_sent", 0)),
            conversation_turns=int(outcome.get("conversation_turns", 0)),
            notes=outcome.get("notes"),
        )
        self._db.add(record)
        await self._db.flush()
        await self._db.refresh(record)

        logger.info(
            "StrategyOutcome stored: id=%s lead=%s recovered=%s",
            record.id,
            lead_id,
            record.deal_recovered,
        )

        # Refresh patterns async (fire and forget — errors are logged, not raised)
        try:
            await self.refresh_patterns(
                organization_id=organization_id,
                industry=record.industry,
            )
        except Exception as exc:
            logger.warning("Pattern refresh failed after outcome store: %s", exc)

        # Index into historical_cases for semantic retrieval
        try:
            await self._index_historical_case(record)
        except Exception as exc:
            logger.warning("Historical case indexing failed: %s", exc)

        return record

    # ------------------------------------------------------------------
    # 2. Pattern aggregation
    # ------------------------------------------------------------------

    async def refresh_patterns(
        self,
        organization_id: uuid.UUID | None = None,
        industry: str | None = None,
    ) -> list[StrategyPattern]:
        """
        Recompute strategy patterns from raw outcomes.
        Called after every new outcome, and can be scheduled periodically.
        """
        patterns: list[StrategyPattern] = []

        # Channel patterns per industry
        patterns.extend(
            await self._compute_channel_patterns(organization_id, industry)
        )

        # Objection patterns
        patterns.extend(
            await self._compute_objection_patterns(organization_id, industry)
        )

        # Deal size patterns
        patterns.extend(
            await self._compute_deal_size_patterns(organization_id, industry)
        )

        logger.info("Pattern refresh complete: %d patterns upserted", len(patterns))
        return patterns

    async def get_patterns_for_planner(
        self,
        organization_id: uuid.UUID,
        industry: str | None = None,
        min_confidence: float = 0.60,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Return top patterns for the Planner to inject into its prompt.
        Merges org-specific and global patterns; org-specific wins on conflict.
        """
        stmt = (
            select(StrategyPattern)
            .where(
                StrategyPattern.confidence_score >= min_confidence,
                StrategyPattern.sample_size >= 3,
            )
            .order_by(
                StrategyPattern.confidence_score.desc(),
                StrategyPattern.sample_size.desc(),
            )
            .limit(limit)
        )

        # Get org-specific + global
        from sqlalchemy import or_, null
        stmt = stmt.where(
            or_(
                StrategyPattern.organization_id == organization_id,
                StrategyPattern.organization_id.is_(None),
            )
        )
        if industry:
            from sqlalchemy import or_ as or2
            stmt = stmt.where(
                or2(
                    StrategyPattern.industry == industry,
                    StrategyPattern.industry.is_(None),
                )
            )

        result = await self._db.execute(stmt)
        patterns = result.scalars().all()

        return [
            {
                "pattern_type": p.pattern_type,
                "pattern_key": p.pattern_key,
                "industry": p.industry,
                "success_rate": p.success_rate,
                "sample_size": p.sample_size,
                "recommended_strategy": p.recommended_strategy,
                "confidence_score": p.confidence_score,
            }
            for p in patterns
        ]

    # ------------------------------------------------------------------
    # 3. Historical case indexing
    # ------------------------------------------------------------------

    async def _index_historical_case(self, outcome: StrategyOutcome) -> HistoricalCase:
        """
        Build a text summary of the outcome and store it with an embedding
        in historical_cases for semantic retrieval.
        """
        context_text = self._build_case_context_text(outcome)
        case_summary = self._build_case_summary(outcome)
        winning_strategy = self._build_winning_strategy(outcome) if outcome.deal_recovered else None

        # Get embedding from OpenAI
        try:
            embedding = await self._retrieval.embed_text(context_text)
        except Exception as exc:
            logger.warning("Embedding failed; storing case without vector: %s", exc)
            embedding = None

        case = HistoricalCase(
            organization_id=outcome.organization_id,
            strategy_outcome_id=outcome.id,
            context_text=context_text,
            industry=outcome.industry,
            deal_value=outcome.deal_value,
            primary_objection=outcome.objection_type,
            channel_used=outcome.channel_used,
            outcome_positive=outcome.deal_recovered,
            revenue_recovered=outcome.revenue_closed if outcome.deal_recovered else None,
            case_summary=case_summary,
            winning_strategy=winning_strategy,
        )
        self._db.add(case)
        await self._db.flush()
        await self._db.refresh(case)

        # Store the embedding via raw SQL (pgvector)
        if embedding:
            try:
                vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
                await self._db.execute(  # type: ignore[arg-type]
                    f"UPDATE historical_cases SET embedding = '{vec_str}'::vector "
                    f"WHERE id = '{case.id}'"
                )
            except Exception as exc:
                logger.warning("Failed to write embedding to historical_cases: %s", exc)

        logger.info("HistoricalCase indexed: id=%s outcome=%s", case.id, outcome.id)
        return case

    # ------------------------------------------------------------------
    # Pattern computation helpers
    # ------------------------------------------------------------------

    async def _compute_channel_patterns(
        self,
        organization_id: uuid.UUID | None,
        industry: str | None,
    ) -> list[StrategyPattern]:
        """Response rate by channel for a given industry."""
        stmt = select(
            StrategyOutcome.channel_used,
            StrategyOutcome.industry,
            func.count().label("total"),
            func.sum(
                func.cast(StrategyOutcome.response_received, Integer := _int_cast())
            ).label("responses"),
            func.sum(
                func.cast(StrategyOutcome.deal_recovered, Integer := _int_cast())
            ).label("recoveries"),
        ).group_by(StrategyOutcome.channel_used, StrategyOutcome.industry)

        if organization_id:
            stmt = stmt.where(StrategyOutcome.organization_id == organization_id)
        if industry:
            stmt = stmt.where(StrategyOutcome.industry == industry)

        result = await self._db.execute(stmt)
        rows = result.mappings().all()

        patterns: list[StrategyPattern] = []
        for row in rows:
            total = row["total"] or 0
            recoveries = int(row["recoveries"] or 0)
            if total < 3:
                continue
            success_rate = recoveries / total
            confidence = min(0.99, 0.5 + (total / 100) * 0.5)

            pattern = await self._upsert_pattern(
                organization_id=organization_id,
                industry=row["industry"],
                pattern_type=PatternType.CHANNEL,
                pattern_key=str(row["channel_used"]),
                success_rate=success_rate,
                sample_size=total,
                recommended_strategy={
                    "primary_channel": row["channel_used"],
                    "reason": f"{success_rate:.0%} recovery rate on {total} campaigns",
                },
                confidence_score=confidence,
            )
            patterns.append(pattern)

        return patterns

    async def _compute_objection_patterns(
        self,
        organization_id: uuid.UUID | None,
        industry: str | None,
    ) -> list[StrategyPattern]:
        """Recovery rate by objection type."""
        from sqlalchemy import Integer as SAInteger, cast

        stmt = select(
            StrategyOutcome.objection_type,
            StrategyOutcome.industry,
            StrategyOutcome.channel_used,
            func.count().label("total"),
            func.sum(cast(StrategyOutcome.deal_recovered, SAInteger)).label("recoveries"),
            func.sum(cast(StrategyOutcome.discount_offered, SAInteger)).label("discounts"),
        ).where(
            StrategyOutcome.objection_type.isnot(None)
        ).group_by(
            StrategyOutcome.objection_type,
            StrategyOutcome.industry,
            StrategyOutcome.channel_used,
        )

        if organization_id:
            stmt = stmt.where(StrategyOutcome.organization_id == organization_id)
        if industry:
            stmt = stmt.where(StrategyOutcome.industry == industry)

        result = await self._db.execute(stmt)
        rows = result.mappings().all()

        patterns: list[StrategyPattern] = []
        for row in rows:
            total = row["total"] or 0
            recoveries = int(row["recoveries"] or 0)
            discounts = int(row["discounts"] or 0)
            if total < 3:
                continue
            success_rate = recoveries / total
            confidence = min(0.99, 0.5 + (total / 50) * 0.5)

            pattern = await self._upsert_pattern(
                organization_id=organization_id,
                industry=row["industry"],
                pattern_type=PatternType.OBJECTION,
                pattern_key=f"{row['objection_type']}::{row['channel_used']}",
                success_rate=success_rate,
                sample_size=total,
                recommended_strategy={
                    "objection_type": row["objection_type"],
                    "best_channel": row["channel_used"],
                    "offer_discount": (discounts / total) > 0.5,
                    "success_rate": success_rate,
                },
                confidence_score=confidence,
            )
            patterns.append(pattern)

        return patterns

    async def _compute_deal_size_patterns(
        self,
        organization_id: uuid.UUID | None,
        industry: str | None,
    ) -> list[StrategyPattern]:
        """Recovery patterns segmented by deal size bucket."""
        from sqlalchemy import Integer as SAInteger, cast, case as sa_case

        bucket_expr = sa_case(
            (StrategyOutcome.deal_value < 1000, "small"),
            (StrategyOutcome.deal_value < 10000, "medium"),
            (StrategyOutcome.deal_value < 50000, "large"),
            else_="enterprise",
        )

        stmt = select(
            bucket_expr.label("deal_bucket"),
            StrategyOutcome.industry,
            func.count().label("total"),
            func.sum(cast(StrategyOutcome.deal_recovered, SAInteger)).label("recoveries"),
            func.sum(cast(StrategyOutcome.human_escalated, SAInteger)).label("escalations"),
            func.avg(StrategyOutcome.time_to_response_hours).label("avg_time_to_response"),
        ).group_by(bucket_expr, StrategyOutcome.industry)

        if organization_id:
            stmt = stmt.where(StrategyOutcome.organization_id == organization_id)
        if industry:
            stmt = stmt.where(StrategyOutcome.industry == industry)

        result = await self._db.execute(stmt)
        rows = result.mappings().all()

        patterns: list[StrategyPattern] = []
        for row in rows:
            total = row["total"] or 0
            recoveries = int(row["recoveries"] or 0)
            escalations = int(row["escalations"] or 0)
            if total < 3:
                continue
            success_rate = recoveries / total
            confidence = min(0.99, 0.4 + (total / 80) * 0.6)

            pattern = await self._upsert_pattern(
                organization_id=organization_id,
                industry=row["industry"],
                pattern_type=PatternType.DEAL_SIZE,
                pattern_key=str(row["deal_bucket"]),
                success_rate=success_rate,
                sample_size=total,
                recommended_strategy={
                    "deal_bucket": row["deal_bucket"],
                    "human_escalation_rate": escalations / total,
                    "recommend_human_escalation": (escalations / total) > 0.4,
                    "avg_time_to_response_hours": (
                        float(row["avg_time_to_response"]) if row["avg_time_to_response"] else None
                    ),
                },
                confidence_score=confidence,
            )
            patterns.append(pattern)

        return patterns

    async def _upsert_pattern(
        self,
        organization_id: uuid.UUID | None,
        industry: str | None,
        pattern_type: PatternType,
        pattern_key: str,
        success_rate: float,
        sample_size: int,
        recommended_strategy: dict[str, Any],
        confidence_score: float,
    ) -> StrategyPattern:
        """
        Upsert a StrategyPattern using PostgreSQL ON CONFLICT DO UPDATE.
        """
        stmt = (
            pg_insert(StrategyPattern)
            .values(
                id=uuid.uuid4(),
                organization_id=organization_id,
                industry=industry,
                pattern_type=pattern_type,
                pattern_key=pattern_key,
                success_rate=success_rate,
                sample_size=sample_size,
                recommended_strategy=recommended_strategy,
                confidence_score=confidence_score,
                last_computed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["organization_id", "industry", "pattern_type", "pattern_key"],
                set_={
                    "success_rate": success_rate,
                    "sample_size": sample_size,
                    "recommended_strategy": recommended_strategy,
                    "confidence_score": confidence_score,
                    "last_computed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(StrategyPattern)
        )
        result = await self._db.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_case_context_text(o: StrategyOutcome) -> str:
        return (
            f"Industry: {o.industry or 'unknown'}. "
            f"Lead type: {o.lead_type or 'unknown'}. "
            f"Deal value: ${o.deal_value or 0:,.0f}. "
            f"Objection: {o.objection_type or 'none'}. "
            f"Strategy: {o.strategy_used or 'default'}. "
            f"Channel: {o.channel_used}. "
            f"Discount offered: {o.discount_offered}. "
            f"Human escalated: {o.human_escalated}. "
            f"Response received: {o.response_received}. "
            f"Deal recovered: {o.deal_recovered}. "
            f"Revenue closed: ${o.revenue_closed or 0:,.0f}."
        )

    @staticmethod
    def _build_case_summary(o: StrategyOutcome) -> str:
        outcome_str = "recovered $" + f"{o.revenue_closed:,.0f}" if o.deal_recovered and o.revenue_closed else (
            "response received" if o.response_received else "no response"
        )
        return (
            f"{o.industry or 'Unknown industry'} lead "
            f"with ${o.deal_value or 0:,.0f} deal. "
            f"Objection: {o.objection_type or 'none'}. "
            f"Used {o.channel_used} channel. "
            f"Outcome: {outcome_str}."
        )

    @staticmethod
    def _build_winning_strategy(o: StrategyOutcome) -> dict[str, Any]:
        return {
            "primary_channel": o.channel_used,
            "sequence": o.sequence_used,
            "discount_offered": o.discount_offered,
            "human_escalated": o.human_escalated,
            "time_to_response_hours": o.time_to_response_hours,
        }


def _int_cast():
    """Alias to avoid import collision in list comprehension."""
    from sqlalchemy import Integer
    return Integer
