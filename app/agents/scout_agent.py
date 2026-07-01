import json
import logging
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger, has_recent_run
from app.config import get_settings
from app.db.models.agent_run import AgentName
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.organization import Organization

logger = logging.getLogger(__name__)
settings = get_settings()


class ExternalSignalService:
    """Fetch buying signals from Apollo.io and Crunchbase."""

    async def fetch_company_signals(self, company_name: str) -> dict:
        signals: dict = {"funding": [], "job_changes": [], "growth_events": []}

        if settings.apollo_api_key and company_name:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.apollo.io/v1/mixed_companies/search",
                    headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
                    json={"api_key": settings.apollo_api_key, "q_organization_name": company_name, "page": 1, "per_page": 1},
                )
                if response.status_code == 200:
                    orgs = response.json().get("organizations", [])
                    if orgs:
                        org = orgs[0]
                        if org.get("latest_funding_stage"):
                            signals["funding"].append(
                                {"stage": org["latest_funding_stage"], "amount": org.get("total_funding")}
                            )
                        if org.get("estimated_num_employees"):
                            signals["growth_events"].append(
                                {"type": "headcount", "value": org["estimated_num_employees"]}
                            )

        if settings.crunchbase_api_key and company_name:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    "https://api.crunchbase.com/api/v4/autocompletes",
                    params={"query": company_name, "collection_ids": "organizations", "limit": 1},
                    headers={"X-cb-user-key": settings.crunchbase_api_key},
                )
                if response.status_code == 200:
                    entities = response.json().get("entities", [])
                    if entities:
                        signals["growth_events"].append({"type": "crunchbase_match", "entity": entities[0].get("identifier", {})})

        return signals


class ScoutAgent:
    """Detect external buying signals and re-score dormant leads."""

    AGENT_NAME = AgentName.SCOUT

    def __init__(self, db: Session) -> None:
        self.db = db
        self.signals = ExternalSignalService()

    def run(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        import asyncio

        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        if has_recent_run(self.db, organization_id, self.AGENT_NAME, within_minutes=720):
            return {"skipped": True, "reason": "duplicate_run"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            stmt = select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.lead_status == LeadStatus.DORMANT,
            )
            leads = self.db.execute(stmt).scalars().all()
            priority_updates = 0
            new_signals: list[dict] = []

            for lead in leads:
                if not lead.company:
                    continue
                signals = asyncio.run(self.signals.fetch_company_signals(lead.company))
                signal_count = sum(len(v) for v in signals.values())
                if signal_count == 0:
                    continue

                boost = min(signal_count * 15, 50)
                lead.priority_score = min(lead.priority_score + boost, 100)
                priority_updates += 1

                latest_analysis = self.db.execute(
                    select(LeadAnalysis)
                    .where(LeadAnalysis.lead_id == lead.id)
                    .order_by(LeadAnalysis.analyzed_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                if latest_analysis:
                    current_prob = float(latest_analysis.recovery_probability or 0)
                    new_prob = min(current_prob + (boost / 100), 0.95)
                    latest_analysis.recovery_probability = Decimal(str(round(new_prob, 4)))
                    latest_analysis.buying_signals = json.dumps(signals)

                new_signals.append({"lead_id": str(lead.id), "company": lead.company, "signals": signals})

            self.db.commit()
            result = {
                "leads_scanned": len(leads),
                "priority_updates": priority_updates,
                "new_opportunity_signals": new_signals[:50],
            }
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise
