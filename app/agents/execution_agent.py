import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger
from app.db.models.agent_run import AgentName
from app.db.models.campaign import Campaign, CampaignChannel, CampaignStatus
from app.db.models.lead import Lead
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.organization import Organization
from app.services.messaging.email_service import EmailService
from app.services.messaging.sms_service import SMSService

logger = logging.getLogger(__name__)


class ExecutionAgent:
    """Autonomous message delivery with channel escalation logic."""

    AGENT_NAME = AgentName.EXECUTION
    EMAIL_WAIT_DAYS = 3
    SMS_WAIT_DAYS = 7

    def __init__(self, db: Session) -> None:
        self.db = db
        self.email_service = EmailService()
        self.sms_service = SMSService()

    def run(
        self,
        organization_id: UUID,
        lead_ids: list[UUID] | None = None,
        celery_task_id: str | None = None,
    ) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled or not org.auto_send_enabled:
            return {"skipped": True, "reason": "auto_send_disabled"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            if lead_ids:
                stmt = select(Lead).where(Lead.organization_id == organization_id, Lead.id.in_(lead_ids))
            else:
                stmt = select(Lead).where(Lead.organization_id == organization_id)

            leads = self.db.execute(stmt).scalars().all()
            sent_count = 0
            results: list[dict] = []

            for lead in leads:
                channel = self._choose_channel(lead)
                if not channel:
                    continue

                message_data = self._get_message_content(lead)
                if not message_data:
                    continue

                campaign = Campaign(
                    organization_id=organization_id,
                    lead_id=lead.id,
                    channel=channel,
                    subject_line=message_data.get("subject_line"),
                    message_content=message_data.get(f"{channel}_body") or message_data.get("email_body", ""),
                    status=CampaignStatus.SCHEDULED,
                )
                self.db.add(campaign)
                self.db.flush()

                try:
                    external_id = self._send(campaign, lead, message_data)
                    campaign.status = CampaignStatus.SENT
                    campaign.sent_at = datetime.now(UTC)
                    campaign.external_message_id = external_id
                    sent_count += 1
                    results.append({"lead_id": str(lead.id), "channel": channel, "campaign_id": str(campaign.id)})
                except Exception as exc:
                    campaign.status = CampaignStatus.FAILED
                    logger.error("Campaign send failed for lead %s: %s", lead.id, exc)

            self.db.commit()
            result = {"campaigns_sent": sent_count, "results": results}
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise

    def _choose_channel(self, lead: Lead) -> str | None:
        campaigns = self.db.execute(
            select(Campaign)
            .where(Campaign.lead_id == lead.id)
            .order_by(Campaign.sent_at.desc())
        ).scalars().all()

        if not campaigns:
            return CampaignChannel.EMAIL if lead.email else (CampaignChannel.SMS if lead.phone else None)

        latest = campaigns[0]
        if latest.responded_at:
            return None

        now = datetime.now(UTC)
        if latest.channel == CampaignChannel.EMAIL and latest.sent_at:
            if (now - latest.sent_at).days >= self.EMAIL_WAIT_DAYS and lead.phone:
                return CampaignChannel.SMS
        elif latest.channel == CampaignChannel.SMS and latest.sent_at:
            if (now - latest.sent_at).days >= self.SMS_WAIT_DAYS and lead.phone:
                return CampaignChannel.WHATSAPP

        if latest.status == CampaignStatus.FAILED and lead.email:
            return CampaignChannel.EMAIL

        return None

    def _get_message_content(self, lead: Lead) -> dict | None:
        analysis = self.db.execute(
            select(LeadAnalysis)
            .where(LeadAnalysis.lead_id == lead.id)
            .order_by(LeadAnalysis.analyzed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not analysis or not analysis.recommended_message:
            return None

        try:
            return json.loads(analysis.recommended_message)
        except json.JSONDecodeError:
            return {
                "email_body": analysis.recommended_message,
                "sms_body": analysis.recommended_message[:320],
                "whatsapp_body": analysis.recommended_message,
                "subject_line": f"Reconnecting — {lead.company or lead.full_name}",
            }

    def _send(self, campaign: Campaign, lead: Lead, message_data: dict) -> str:
        if campaign.channel == CampaignChannel.EMAIL:
            if not lead.email:
                raise ValueError("Lead has no email")
            return self.email_service.send_via_sendgrid(
                lead.email,
                message_data.get("subject_line", "Following up"),
                message_data.get("email_body", campaign.message_content),
            )
        if campaign.channel == CampaignChannel.SMS:
            if not lead.phone:
                raise ValueError("Lead has no phone")
            return self.sms_service.send_sms(lead.phone, message_data.get("sms_body", campaign.message_content))
        if campaign.channel == CampaignChannel.WHATSAPP:
            if not lead.phone:
                raise ValueError("Lead has no phone for WhatsApp")
            return self.sms_service.send_sms(lead.phone, message_data.get("whatsapp_body", campaign.message_content))
        raise ValueError(f"Unknown channel: {campaign.channel}")
