"""
Agent tool implementations.

Each function is independently callable and async.
Planner and other agents call these to gather missing context
before finalising decisions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import StrategyOutcome, StrategyPattern

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool: check_previous_campaign_performance
# ---------------------------------------------------------------------------

async def check_previous_campaign_performance(
    db: AsyncSession,
    lead_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """
    Returns aggregated campaign performance for a specific lead.
    """
    try:
        uid = UUID(lead_id)
        org_uid = UUID(organization_id)
    except ValueError:
        return {"error": "invalid uuid"}

    stmt = select(StrategyOutcome).where(
        StrategyOutcome.lead_id == uid,
        StrategyOutcome.organization_id == org_uid,
    )
    result = await db.execute(stmt)
    outcomes = result.scalars().all()

    if not outcomes:
        return {
            "total_campaigns": 0,
            "response_rate": 0.0,
            "recovery_rate": 0.0,
            "best_channel": None,
            "channels_tried": [],
        }

    total = len(outcomes)
    responded = sum(1 for o in outcomes if o.response_received)
    recovered = sum(1 for o in outcomes if o.deal_recovered)
    channel_counts: dict[str, int] = {}
    for o in outcomes:
        channel_counts[o.channel_used] = channel_counts.get(o.channel_used, 0) + 1

    best_channel = max(channel_counts, key=lambda k: channel_counts[k]) if channel_counts else None

    return {
        "total_campaigns": total,
        "response_rate": round(responded / total, 3),
        "recovery_rate": round(recovered / total, 3),
        "best_channel": best_channel,
        "channels_tried": list(channel_counts.keys()),
        "avg_time_to_response_hours": _safe_avg(
            [o.time_to_response_hours for o in outcomes if o.time_to_response_hours]
        ),
    }


# ---------------------------------------------------------------------------
# Tool: get_industry_benchmarks
# ---------------------------------------------------------------------------

async def get_industry_benchmarks(
    db: AsyncSession,
    industry: str,
) -> dict[str, Any]:
    """
    Retrieves aggregated strategy patterns for the given industry.
    """
    stmt = select(StrategyPattern).where(
        StrategyPattern.industry == industry,
        StrategyPattern.sample_size >= 5,
    )
    result = await db.execute(stmt)
    patterns = result.scalars().all()

    if not patterns:
        return {"industry": industry, "patterns": [], "message": "no_data"}

    return {
        "industry": industry,
        "patterns": [
            {
                "pattern_type": p.pattern_type,
                "pattern_key": p.pattern_key,
                "success_rate": p.success_rate,
                "sample_size": p.sample_size,
                "recommended_strategy": p.recommended_strategy,
                "confidence_score": p.confidence_score,
            }
            for p in patterns
        ],
    }


# ---------------------------------------------------------------------------
# Tool: retrieve_similar_historical_cases
# ---------------------------------------------------------------------------

async def retrieve_similar_historical_cases(
    db: AsyncSession,
    embedding: list[float],
    industry: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Semantic search against historical_cases via pgvector.
    Falls back to metadata-only query if pgvector extension is unavailable.
    """
    from app.models.intelligence import HistoricalCase

    try:
        # pgvector cosine distance — requires pgvector extension installed
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        filters = ""
        if industry:
            filters = f"AND industry = '{industry.replace(chr(39), '')}'"

        raw_sql = f"""
            SELECT id, case_summary, winning_strategy, outcome_positive,
                   industry, deal_value, primary_objection, channel_used,
                   1 - (embedding <=> '{vec_str}'::vector) AS similarity
            FROM historical_cases
            WHERE 1=1 {filters}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {limit}
        """
        result = await db.execute(raw_sql)  # type: ignore[arg-type]
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    except Exception as exc:
        logger.warning("pgvector query failed (%s); falling back to metadata filter", exc)
        stmt = select(HistoricalCase)
        if industry:
            stmt = stmt.where(HistoricalCase.industry == industry)
        stmt = stmt.order_by(HistoricalCase.created_at.desc()).limit(limit)
        result2 = await db.execute(stmt)
        cases = result2.scalars().all()
        return [
            {
                "id": str(c.id),
                "case_summary": c.case_summary,
                "winning_strategy": c.winning_strategy,
                "outcome_positive": c.outcome_positive,
                "industry": c.industry,
                "deal_value": c.deal_value,
                "primary_objection": c.primary_objection,
                "channel_used": c.channel_used,
                "similarity": None,
            }
            for c in cases
        ]


# ---------------------------------------------------------------------------
# Tool: check_customer_previous_open_rates
# ---------------------------------------------------------------------------

async def check_customer_previous_open_rates(
    db: AsyncSession,
    lead_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """
    Returns per-channel engagement proxy from outcome history.
    In a production system this would query your email/SMS platform.
    Here we derive engagement signals from StrategyOutcome.
    """
    try:
        uid = UUID(lead_id)
        org_uid = UUID(organization_id)
    except ValueError:
        return {"error": "invalid uuid"}

    stmt = select(StrategyOutcome).where(
        StrategyOutcome.lead_id == uid,
        StrategyOutcome.organization_id == org_uid,
        StrategyOutcome.response_received.is_(True),
    )
    result = await db.execute(stmt)
    outcomes = result.scalars().all()

    channel_success: dict[str, int] = {}
    for o in outcomes:
        channel_success[o.channel_used] = channel_success.get(o.channel_used, 0) + 1

    total = sum(channel_success.values())
    return {
        "lead_id": lead_id,
        "channel_response_counts": channel_success,
        "best_responding_channel": (
            max(channel_success, key=lambda k: channel_success[k])
            if channel_success
            else None
        ),
        "total_responses_on_record": total,
    }


# ---------------------------------------------------------------------------
# Tool: analyze_company_external_signals
# ---------------------------------------------------------------------------

async def analyze_company_external_signals(
    company_name: str,
    domain: str | None = None,
) -> dict[str, Any]:
    """
    Placeholder for external signal enrichment (Clearbit, LinkedIn, etc.).
    Returns a structured signal dict; replace body with real API calls.
    """
    # TODO: integrate Clearbit / Apollo / LinkedIn enrichment API
    return {
        "company_name": company_name,
        "domain": domain,
        "funding_signal": "unknown",
        "headcount_growth": "unknown",
        "tech_stack_signals": [],
        "recent_news": [],
        "enrichment_available": False,
        "note": "External enrichment not yet configured; plug in Clearbit/Apollo here.",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None
