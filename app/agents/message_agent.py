import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger
from app.agents.prompts.message import MESSAGE_SYSTEM_PROMPT
from app.db.models.agent_run import AgentName
from app.db.models.lead import Lead
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.organization import Organization
from app.services.llm.llm_service import LLMService

logger = logging.getLogger(__name__)


class MessageAgent:
    """Generate personalized outreach across channels."""

    AGENT_NAME = AgentName.MESSAGE

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = LLMService()

    def run(
        self,
        organization_id: UUID,
        lead_ids: list[UUID] | None = None,
        celery_task_id: str | None = None,
    ) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            if lead_ids:
                stmt = select(Lead).where(Lead.organization_id == organization_id, Lead.id.in_(lead_ids))
            else:
                stmt = select(Lead).where(Lead.organization_id == organization_id)

            leads = self.db.execute(stmt).scalars().all()
            messages_generated = 0
            outputs: list[dict] = []

            for lead in leads:
                analysis = self.db.execute(
                    select(LeadAnalysis)
                    .where(LeadAnalysis.lead_id == lead.id)
                    .order_by(LeadAnalysis.analyzed_at.desc())
                    .limit(1)
                ).scalar_one_or_none()

                if not analysis:
                    continue

                user_prompt = json.dumps(
                    {
                        "lead": {"full_name": lead.full_name, "company": lead.company, "email": lead.email},
                        "analysis": {
                            "reason_lead_died": analysis.reason_lead_died,
                            "recovery_probability": float(analysis.recovery_probability or 0),
                            "recommended_strategy": analysis.recommended_strategy,
                            "recommended_message": analysis.recommended_message,
                        },
                        "company_name": org.company_name,
                    }
                )
                message_data = self.llm.complete_json(MESSAGE_SYSTEM_PROMPT, user_prompt)
                analysis.recommended_message = json.dumps(message_data)
                messages_generated += 1
                outputs.append({"lead_id": str(lead.id), **message_data})

            self.db.commit()
            result = {"messages_generated": messages_generated, "outputs": outputs}
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise
