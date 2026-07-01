"""
Intelligence layer Celery tasks.

Integrates PLANNER, MEMORY, and CONVERSATIONAL agents into the
existing Revio AI Celery worker infrastructure.

Import these tasks in your existing celery app:
    from app.tasks.intelligence_tasks import (
        run_planner_task,
        store_outcome_task,
        refresh_patterns_task,
        handle_lead_reply_task,
        index_historical_case_task,
    )

All tasks are async-compatible via anyio.from_thread.run_sync or
the synchronous wrapper pattern below.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.agents.conversational_agent import ConversationalAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.planner_agent import PlannerAgent
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — bridge sync Celery → async agents
# ---------------------------------------------------------------------------

def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _get_db_session():
    """
    Returns an AsyncSession from the existing Revio DB engine.
    Replace with your actual session factory import.

    Example:
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            yield session
    """
    raise NotImplementedError(
        "Inject your AsyncSessionLocal from app.db.session here"
    )


def _get_openai_key() -> str:
    """Return OpenAI API key from settings. Replace with your settings import."""
    import os
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY not set")
    return key


# ---------------------------------------------------------------------------
# Task: run_planner_task
# ---------------------------------------------------------------------------

def run_planner_task(
    celery_app: Any,
    lead_data: dict[str, Any],
    crm_data: dict[str, Any],
    organization_id: str,
    lead_id: str,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """
    Celery task body — run PLANNER AGENT for a lead.

    Register with your celery app:
        @celery_app.task(name="run_planner", bind=True, max_retries=3)
        def run_planner(self, lead_data, crm_data, organization_id, lead_id, campaign_id=None):
            return run_planner_task(self.app, lead_data, crm_data, organization_id, lead_id, campaign_id)
    """
    async def _run() -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal  # type: ignore[import]

        org_uuid = uuid.UUID(organization_id)
        lead_uuid = uuid.UUID(lead_id)
        campaign_uuid = uuid.UUID(campaign_id) if campaign_id else None
        api_key = _get_openai_key()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Fetch memory patterns for this org/industry
                memory = MemoryAgent(api_key, session)
                patterns = await memory.get_patterns_for_planner(
                    organization_id=org_uuid,
                    industry=lead_data.get("industry"),
                )

                # Run planner
                planner = PlannerAgent(api_key, session)
                try:
                    result = await planner.plan(lead_data, crm_data, patterns)
                    plan = await planner.persist_plan(
                        result=result,
                        organization_id=org_uuid,
                        lead_id=lead_uuid,
                        db=session,
                        campaign_id=campaign_uuid,
                    )
                finally:
                    await planner.close()

                return {
                    "plan_id": str(plan.id),
                    "contact_lead": plan.contact_lead,
                    "primary_channel": plan.primary_channel,
                    "delay_hours": plan.delay_hours,
                    "human_escalation": plan.human_escalation,
                    "offer_discount": plan.offer_discount,
                    "sequence": plan.sequence,
                    "confidence_score": plan.confidence_score,
                    "reasoning": plan.reasoning,
                    "iterations": plan.reasoning_iterations,
                }

    return _run_async(_run())


# ---------------------------------------------------------------------------
# Task: store_outcome_task
# ---------------------------------------------------------------------------

def store_outcome_task(
    outcome: dict[str, Any],
    organization_id: str,
    lead_id: str,
    execution_plan_id: str | None = None,
) -> dict[str, Any]:
    """
    Celery task body — store campaign outcome in MEMORY AGENT.

    Register:
        @celery_app.task(name="store_outcome", bind=True, max_retries=2)
        def store_outcome(self, outcome, organization_id, lead_id, execution_plan_id=None):
            return store_outcome_task(outcome, organization_id, lead_id, execution_plan_id)
    """
    async def _run() -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal  # type: ignore[import]

        org_uuid = uuid.UUID(organization_id)
        lead_uuid = uuid.UUID(lead_id)
        plan_uuid = uuid.UUID(execution_plan_id) if execution_plan_id else None
        api_key = _get_openai_key()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                memory = MemoryAgent(api_key, session)
                record = await memory.store_outcome(
                    organization_id=org_uuid,
                    lead_id=lead_uuid,
                    outcome=outcome,
                    execution_plan_id=plan_uuid,
                )
                return {"outcome_id": str(record.id), "deal_recovered": record.deal_recovered}

    return _run_async(_run())


# ---------------------------------------------------------------------------
# Task: refresh_patterns_task
# ---------------------------------------------------------------------------

def refresh_patterns_task(
    organization_id: str | None = None,
    industry: str | None = None,
) -> dict[str, Any]:
    """
    Periodic task — recompute strategy patterns.
    Schedule with celery beat every 6 hours.
    """
    async def _run() -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal  # type: ignore[import]

        org_uuid = uuid.UUID(organization_id) if organization_id else None
        api_key = _get_openai_key()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                memory = MemoryAgent(api_key, session)
                patterns = await memory.refresh_patterns(
                    organization_id=org_uuid,
                    industry=industry,
                )
                return {"patterns_refreshed": len(patterns)}

    return _run_async(_run())


# ---------------------------------------------------------------------------
# Task: handle_lead_reply_task
# ---------------------------------------------------------------------------

def handle_lead_reply_task(
    organization_id: str,
    lead_id: str,
    incoming_message: str,
    channel: str = "email",
    execution_plan_id: str | None = None,
) -> dict[str, Any]:
    """
    Celery task body — handle an incoming lead reply via CONVERSATIONAL AGENT.
    Called by webhook receivers (email provider, SMS, WhatsApp).

    Register:
        @celery_app.task(name="handle_lead_reply", bind=True, max_retries=3)
        def handle_lead_reply(self, organization_id, lead_id, message, channel="email", plan_id=None):
            return handle_lead_reply_task(organization_id, lead_id, message, channel, plan_id)
    """
    async def _run() -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal  # type: ignore[import]

        org_uuid = uuid.UUID(organization_id)
        lead_uuid = uuid.UUID(lead_id)
        plan_uuid = uuid.UUID(execution_plan_id) if execution_plan_id else None
        api_key = _get_openai_key()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                agent = ConversationalAgent(api_key, session)
                try:
                    result = await agent.handle_reply(
                        organization_id=org_uuid,
                        lead_id=lead_uuid,
                        incoming_message=incoming_message,
                        channel=channel,
                        execution_plan_id=plan_uuid,
                    )
                finally:
                    await agent.close()

                return result

    return _run_async(_run())


# ---------------------------------------------------------------------------
# Task: index_historical_case_task
# ---------------------------------------------------------------------------

def index_historical_case_task(
    strategy_outcome_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """
    Standalone task to (re-)index a StrategyOutcome into historical_cases.
    Useful for backfilling existing outcomes after deploying the new system.
    """
    async def _run() -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal  # type: ignore[import]
        from sqlalchemy import select
        from app.models.intelligence import StrategyOutcome

        outcome_uuid = uuid.UUID(strategy_outcome_id)
        api_key = _get_openai_key()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(StrategyOutcome).where(StrategyOutcome.id == outcome_uuid)
                )
                outcome = result.scalar_one_or_none()
                if not outcome:
                    return {"error": "outcome not found", "id": strategy_outcome_id}

                memory = MemoryAgent(api_key, session)
                case = await memory._index_historical_case(outcome)
                return {"case_id": str(case.id), "outcome_id": strategy_outcome_id}

    return _run_async(_run())


# ---------------------------------------------------------------------------
# Celery beat schedule additions (paste into your existing CELERYBEAT_SCHEDULE)
# ---------------------------------------------------------------------------

INTELLIGENCE_BEAT_SCHEDULE: dict[str, Any] = {
    "refresh-strategy-patterns-every-6h": {
        "task": "refresh_patterns",
        "schedule": 6 * 60 * 60,  # 6 hours in seconds
        "kwargs": {},
    },
}
