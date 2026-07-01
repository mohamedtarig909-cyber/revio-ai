"""
PLANNER AGENT — Strategic decision engine.

Decides WHAT strategy to use; does NOT generate messages.
Implements full iterative reasoning loop via ReasoningAgent base.
Integrates with MEMORY agent for historical patterns and retrieval service
for similar cases before committing to a strategy.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_tools.tools import (
    analyze_company_external_signals,
    check_customer_previous_open_rates,
    check_previous_campaign_performance,
    get_industry_benchmarks,
    retrieve_similar_historical_cases,
)
from app.core.reasoning_loop import (
    ReasoningAgent,
    ReasoningContext,
    ReasoningResult,
    ToolDefinition,
)
from app.models.intelligence import ExecutionPlan
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a senior revenue strategist with deep expertise in B2B sales recovery.

Your ONLY job is to decide the optimal strategy for recovering a dormant lead.
You do NOT write messages. You decide strategy.

You have access to:
- CRM history and lead notes
- Previous outreach attempts and their outcomes  
- Detected objection history
- Historical recovery patterns from similar cases
- Industry-level benchmarks
- External company signals

You think step-by-step before deciding.

If you need more information before deciding, set the appropriate needs_* flag to true.

Available channels: email, sms, whatsapp, human

You MUST return valid JSON matching this exact schema:
{
  "contact_lead": <bool>,
  "primary_channel": "<email|sms|whatsapp|human>",
  "delay_hours": <int 0-168>,
  "human_escalation": <bool>,
  "offer_discount": <bool>,
  "sequence": ["<channel>", ...],
  "confidence_score": <float 0.0-1.0>,
  "reasoning": "<detailed strategic reasoning>",
  "needs_campaign_history": <bool>,
  "needs_industry_benchmarks": <bool>,
  "needs_open_rate_data": <bool>,
  "needs_external_signals": <bool>
}
"""


class PlannerAgent(ReasoningAgent):
    """
    Strategic planning agent with iterative reasoning.

    Usage:
        agent = PlannerAgent(openai_api_key=settings.openai_api_key, db=session)
        result = await agent.plan(lead_data, crm_data)
        plan = await agent.persist_plan(result, organization_id, lead_id, db)
    """

    def __init__(
        self,
        openai_api_key: str,
        db: AsyncSession,
        retrieval_service: RetrievalService | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(openai_api_key=openai_api_key, **kwargs)
        self._db = db
        self._retrieval = retrieval_service or RetrievalService(openai_api_key, db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(
        self,
        lead_data: dict[str, Any],
        crm_data: dict[str, Any],
        memory_patterns: list[dict[str, Any]] | None = None,
    ) -> ReasoningResult:
        """
        Run the full planning loop and return a ReasoningResult.
        """
        # Step 1: Retrieve similar historical cases via semantic search
        retrieved_cases = await self._retrieval.retrieve_similar_cases(
            lead_data=lead_data,
            industry=lead_data.get("industry"),
            limit=10,
        )

        # Step 2: Build context
        context = ReasoningContext(
            lead_data=lead_data,
            crm_data=crm_data,
            memory_patterns=memory_patterns or [],
            retrieved_cases=retrieved_cases,
        )

        # Step 3: Run iterative reasoning loop
        result = await self.run(context)

        logger.info(
            "Planner completed: confidence=%.2f iterations=%d channel=%s",
            result.confidence,
            result.iterations,
            result.decision.get("primary_channel"),
        )
        return result

    async def persist_plan(
        self,
        result: ReasoningResult,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        db: AsyncSession,
        campaign_id: uuid.UUID | None = None,
    ) -> ExecutionPlan:
        """
        Persist the planning result to execution_plans table.
        """
        d = result.decision
        plan = ExecutionPlan(
            organization_id=organization_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            contact_lead=bool(d.get("contact_lead", True)),
            primary_channel=d.get("primary_channel", "email"),
            delay_hours=int(d.get("delay_hours", 0)),
            human_escalation=bool(d.get("human_escalation", False)),
            offer_discount=bool(d.get("offer_discount", False)),
            sequence=d.get("sequence", []),
            confidence_score=float(result.confidence),
            reasoning=result.reasoning,
            reasoning_iterations=result.iterations,
            tools_called=result.tools_called,
            raw_planner_output=d,
        )
        db.add(plan)
        await db.flush()
        await db.refresh(plan)
        logger.info("ExecutionPlan persisted: id=%s", plan.id)
        return plan

    # ------------------------------------------------------------------
    # ReasoningAgent interface
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_user_prompt(self, context: ReasoningContext) -> str:
        lead = context.lead_data
        crm = context.crm_data

        # Format retrieved cases concisely
        cases_block = ""
        if context.retrieved_cases:
            cases_block = "\n\nSIMILAR HISTORICAL CASES (most relevant first):\n"
            for i, case in enumerate(context.retrieved_cases[:10], 1):
                sim = case.get("similarity")
                sim_str = f" (similarity: {sim:.2f})" if sim is not None else ""
                cases_block += (
                    f"{i}. {case.get('case_summary', 'N/A')}{sim_str}\n"
                    f"   Outcome: {'✓ Recovered' if case.get('outcome_positive') else '✗ Failed'}"
                    f" | Strategy: {json.dumps(case.get('winning_strategy', {}))}\n"
                )

        # Format memory patterns
        patterns_block = ""
        if context.memory_patterns:
            patterns_block = "\n\nLEARNED PATTERNS FROM MEMORY AGENT:\n"
            for p in context.memory_patterns[:5]:
                patterns_block += (
                    f"- [{p.get('pattern_type')}] {p.get('pattern_key')}: "
                    f"{p.get('success_rate', 0):.0%} success rate "
                    f"(n={p.get('sample_size', 0)})\n"
                    f"  Recommended: {json.dumps(p.get('recommended_strategy', {}))}\n"
                )

        # Format tool results
        tools_block = ""
        if context.tool_results:
            tools_block = "\n\nTOOL RESULTS FROM THIS SESSION:\n"
            for tool_name, data in context.tool_results.items():
                tools_block += f"\n[{tool_name}]\n{json.dumps(data, default=str, indent=2)}\n"

        return f"""
LEAD PROFILE:
- Name: {lead.get('name', 'Unknown')}
- Company: {lead.get('company', 'Unknown')}
- Industry: {lead.get('industry', 'Unknown')}
- Deal value: ${lead.get('deal_value', 0):,.0f}
- Lead type: {lead.get('lead_type', 'Unknown')}
- Days dormant: {lead.get('days_dormant', 0)}
- Previous contact attempts: {lead.get('previous_attempts', 0)}

CRM HISTORY:
- Last activity: {crm.get('last_activity', 'Unknown')}
- Stage: {crm.get('deal_stage', 'Unknown')}
- Objections recorded: {crm.get('objections', [])}
- Notes: {crm.get('notes', 'None')}
- Owner: {crm.get('owner_name', 'Unknown')}

PREVIOUS OUTREACH:
- Emails sent: {crm.get('emails_sent', 0)}
- SMS sent: {crm.get('sms_sent', 0)}
- WhatsApp sent: {crm.get('whatsapp_sent', 0)}
- Last reply received: {crm.get('last_reply', 'None')}
- Response history: {crm.get('response_history', [])}
{cases_block}{patterns_block}{tools_block}

Based on all available data, decide the optimal recovery strategy.
If confidence < 0.80 and you need additional data, set the appropriate needs_* flag to true.
Otherwise commit to a final strategy.
"""

    def parse_response(self, raw: str) -> dict[str, Any]:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )
        return json.loads(clean)

    def get_tools(self) -> list[ToolDefinition]:
        db = self._db
        return [
            ToolDefinition(
                name="check_previous_campaign_performance",
                description="Retrieve previous campaign performance for this lead",
                parameters={"lead_id": "str", "organization_id": "str"},
                handler=lambda lead_id, organization_id: check_previous_campaign_performance(
                    db, lead_id, organization_id
                ),
            ),
            ToolDefinition(
                name="get_industry_benchmarks",
                description="Get industry-level strategy benchmarks",
                parameters={"industry": "str"},
                handler=lambda industry: get_industry_benchmarks(db, industry),
            ),
            ToolDefinition(
                name="check_customer_previous_open_rates",
                description="Get per-channel engagement history for this lead",
                parameters={"lead_id": "str", "organization_id": "str"},
                handler=lambda lead_id, organization_id: check_customer_previous_open_rates(
                    db, lead_id, organization_id
                ),
            ),
            ToolDefinition(
                name="analyze_company_external_signals",
                description="Fetch external signals for the company",
                parameters={"company_name": "str", "domain": "str"},
                handler=lambda company_name, domain=None: analyze_company_external_signals(
                    company_name, domain
                ),
            ),
        ]

    def is_decision_sufficient(self, decision: dict[str, Any]) -> bool:
        """
        A decision is sufficient when:
        1. Confidence meets threshold, AND
        2. No flags requesting additional data are set.
        """
        if decision.get("confidence_score", 0.0) < self.confidence_threshold:
            return False
        needs_more = any(
            decision.get(k, False)
            for k in (
                "needs_campaign_history",
                "needs_industry_benchmarks",
                "needs_open_rate_data",
                "needs_external_signals",
            )
        )
        return not needs_more
