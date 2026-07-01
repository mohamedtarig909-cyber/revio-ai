import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger, has_recent_run
from app.agents.prompts.revive import REVIVE_SYSTEM_PROMPT
from app.config import get_settings
from app.db.models.agent_run import AgentName
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.organization import Organization
from app.services.llm.llm_service import LLMService

logger = logging.getLogger(__name__)
settings = get_settings()


class ReviveAgent:
    """Detect dormant leads and recover lost revenue."""

    AGENT_NAME = AgentName.REVIVE

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = LLMService()

    def run(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        if has_recent_run(self.db, organization_id, self.AGENT_NAME, within_minutes=60):
            return {"skipped": True, "reason": "duplicate_run"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            cutoff = datetime.now(UTC) - timedelta(days=settings.revive_inactivity_days)
            stmt = select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.lead_status.in_([LeadStatus.ACTIVE, LeadStatus.DORMANT]),
                (Lead.last_contact_date <= cutoff) | (Lead.last_contact_date.is_(None)),
            )
            dormant_leads = self.db.execute(stmt).scalars().all()
            analyzed = 0
            high_probability: list[UUID] = []

            for lead in dormant_leads:
                lead.lead_status = LeadStatus.DORMANT
                analysis_result = self._analyze_lead(lead)
                analysis = LeadAnalysis(
                    lead_id=lead.id,
                    recovery_probability=Decimal(str(analysis_result["recovery_probability"])),
                    reason_lead_died=analysis_result["reason_lead_died"],
                    confidence_score=Decimal(str(analysis_result["confidence_score"])),
                    recommended_strategy=analysis_result["recommended_strategy"],
                    recommended_message=analysis_result["recommended_message"],
                )
                self.db.add(analysis)
                analyzed += 1

                if float(analysis_result["recovery_probability"]) >= 0.5:
                    high_probability.append(lead.id)

            self.db.commit()
            result = {
                "dormant_leads_found": len(dormant_leads),
                "analyzed": analyzed,
                "high_probability_lead_ids": [str(lid) for lid in high_probability],
            }
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise

    def _analyze_lead(self, lead: Lead) -> dict:
        user_prompt = json.dumps(
            {
                "lead": {
                    "full_name": lead.full_name,
                    "email": lead.email,
                    "company": lead.company,
                    "deal_value": float(lead.deal_value) if lead.deal_value else None,
                    "pipeline_stage": lead.pipeline_stage,
                    "last_contact_date": lead.last_contact_date.isoformat() if lead.last_contact_date else None,
                    "assigned_rep": lead.assigned_rep,
                    "notes": lead.notes,
                }
            },
            default=str,
        )
        return self.llm.complete_json(REVIVE_SYSTEM_PROMPT, user_prompt)
