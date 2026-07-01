import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger
from app.agents.prompts.report import REPORT_SYSTEM_PROMPT
from app.db.models.agent_run import AgentName, AgentRun
from app.db.models.campaign import Campaign, CampaignStatus
from app.db.models.daily_report import DailyReport
from app.db.models.lead import Lead, LeadStatus
from app.db.models.organization import Organization
from app.db.models.pipeline_health import PipelineHealth
from app.db.models.user import User
from app.services.llm.llm_service import LLMService
from app.services.messaging.email_service import EmailService

logger = logging.getLogger(__name__)


class ResponseAgent:
    """Detect customer engagement from inbound replies."""

    AGENT_NAME = AgentName.RESPONSE

    INTERESTED_KEYWORDS = {"interested", "yes", "schedule", "meeting", "call", "demo", "let's talk", "sounds good"}
    ESCALATION_KEYWORDS = {"unsubscribe", "stop", "legal", "complaint", "angry", "remove me"}

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = LLMService()

    def run(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            stmt = select(Campaign).where(
                Campaign.organization_id == organization_id,
                Campaign.status == CampaignStatus.SENT,
                Campaign.responded_at.is_(None),
            )
            pending = self.db.execute(stmt).scalars().all()
            processed = 0
            reactivated = 0
            escalations = 0

            for campaign in pending:
                inbound = self._check_inbound_reply(campaign)
                if not inbound:
                    continue

                intent = self._analyze_intent(inbound)
                campaign.responded_at = datetime.now(UTC)
                campaign.status = CampaignStatus.RESPONDED
                processed += 1

                lead = self.db.get(Lead, campaign.lead_id)
                if not lead:
                    continue

                if intent.get("needs_human_escalation"):
                    lead.lead_status = LeadStatus.ESCALATED
                    escalations += 1
                elif intent.get("customer_interested") or intent.get("meeting_request_detected"):
                    lead.lead_status = LeadStatus.REACTIVATED
                    lead.last_contact_date = datetime.now(UTC)
                    reactivated += 1

            self.db.commit()
            result = {
                "responses_processed": processed,
                "leads_reactivated": reactivated,
                "escalations": escalations,
            }
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise

    def _check_inbound_reply(self, campaign: Campaign) -> str | None:
        """Poll provider webhooks/inboxes — extend with SendGrid inbound parse & Twilio callbacks."""
        return None

    def process_inbound_webhook(self, organization_id: UUID, channel: str, from_address: str, body: str) -> dict:
        """Handle real-time inbound webhooks from SendGrid/Twilio."""
        lead = self.db.execute(
            select(Lead).where(
                Lead.organization_id == organization_id,
                (Lead.email == from_address) | (Lead.phone == from_address),
            )
        ).scalar_one_or_none()

        if not lead:
            return {"matched": False}

        campaign = self.db.execute(
            select(Campaign)
            .where(Campaign.lead_id == lead.id, Campaign.channel == channel)
            .order_by(Campaign.sent_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        intent = self._analyze_intent(body)
        if campaign:
            campaign.responded_at = datetime.now(UTC)
            campaign.status = CampaignStatus.RESPONDED

        if intent.get("needs_human_escalation"):
            lead.lead_status = LeadStatus.ESCALATED
        elif intent.get("customer_interested"):
            lead.lead_status = LeadStatus.REACTIVATED
            lead.last_contact_date = datetime.now(UTC)

        self.db.commit()
        return {"matched": True, "lead_id": str(lead.id), **intent}

    def _analyze_intent(self, body: str) -> dict:
        lower = body.lower()
        if any(kw in lower for kw in self.ESCALATION_KEYWORDS):
            return {"needs_human_escalation": True, "customer_interested": False, "meeting_request_detected": False}

        interested = any(kw in lower for kw in self.INTERESTED_KEYWORDS)
        meeting = any(kw in lower for kw in {"meeting", "schedule", "calendar", "call"})
        return {
            "customer_interested": interested,
            "meeting_request_detected": meeting,
            "needs_human_escalation": False,
            "lead_reactivated": interested,
        }


class ReportAgent:
    """Generate autonomous daily executive reports."""

    AGENT_NAME = AgentName.REPORT

    def __init__(self, db: Session) -> None:
        self.db = db
        self.llm = LLMService()
        self.email_service = EmailService()

    def run(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        from datetime import timedelta

        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            since = datetime.now(UTC) - timedelta(hours=24)

            agent_runs = self.db.execute(
                select(AgentRun).where(AgentRun.organization_id == organization_id, AgentRun.started_at >= since)
            ).scalars().all()

            reactivated = self.db.execute(
                select(Lead).where(
                    Lead.organization_id == organization_id,
                    Lead.lead_status == LeadStatus.REACTIVATED,
                    Lead.updated_at >= since,
                )
            ).scalars().all()

            campaigns = self.db.execute(
                select(Campaign).where(Campaign.organization_id == organization_id, Campaign.sent_at >= since)
            ).scalars().all()

            pipeline = self.db.execute(
                select(PipelineHealth)
                .where(PipelineHealth.organization_id == organization_id)
                .order_by(PipelineHealth.generated_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            stats = {
                "agent_runs_24h": len(agent_runs),
                "leads_reactivated": len(reactivated),
                "campaigns_sent": len(campaigns),
                "revenue_recovered": sum(float(l.deal_value or 0) for l in reactivated),
                "pipeline_health_score": float(pipeline.pipeline_health_score) if pipeline else None,
                "revenue_at_risk": float(pipeline.revenue_at_risk) if pipeline else 0,
            }

            user_prompt = json.dumps({"company": org.company_name, "stats": stats, "period": "last_24_hours"})
            report_content = self.llm.complete(REPORT_SYSTEM_PROMPT, user_prompt)

            report = DailyReport(organization_id=organization_id, report_content=report_content)
            self.db.add(report)
            self.db.flush()

            owner = self.db.execute(
                select(User).where(User.organization_id == organization_id).limit(1)
            ).scalar_one_or_none()

            if owner:
                html = f"<div style='font-family:sans-serif'>{report_content.replace(chr(10), '<br>')}</div>"
                self.email_service.send_via_resend(
                    owner.email,
                    f"Revio AI Daily Report — {org.company_name}",
                    html,
                )
                report.emailed_at = datetime.now(UTC)

            self.db.commit()
            result = {"report_id": str(report.id), "emailed": owner is not None, **stats}
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise
