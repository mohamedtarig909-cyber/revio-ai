import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger, has_recent_run
from app.config import get_settings
from app.db.models.agent_run import AgentName
from app.db.models.lead import Lead, LeadStatus
from app.db.models.organization import Organization
from app.db.models.pipeline_health import PipelineHealth
from app.services.messaging.email_service import SlackAlertService

logger = logging.getLogger(__name__)
settings = get_settings()

STAGE_STALL_DAYS = 14


class PulseAgent:
    """Monitor pipeline health continuously."""

    AGENT_NAME = AgentName.PULSE

    def __init__(self, db: Session) -> None:
        self.db = db
        self.slack = SlackAlertService()

    def run(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        if has_recent_run(self.db, organization_id, self.AGENT_NAME, within_minutes=90):
            return {"skipped": True, "reason": "duplicate_run"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start()

        try:
            stmt = select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.lead_status.in_([LeadStatus.ACTIVE, LeadStatus.DORMANT]),
            )
            leads = self.db.execute(stmt).scalars().all()

            now = datetime.now(UTC)
            stalled: list[dict] = []
            revenue_at_risk = Decimal("0")
            stage_counts: dict[str, int] = defaultdict(int)

            for lead in leads:
                stage_counts[lead.pipeline_stage or "unknown"] += 1
                if lead.last_contact_date:
                    days_stalled = (now - lead.last_contact_date).days
                    if days_stalled >= STAGE_STALL_DAYS:
                        value = lead.deal_value or Decimal("0")
                        revenue_at_risk += value
                        stalled.append(
                            {
                                "lead_id": str(lead.id),
                                "name": lead.full_name,
                                "stage": lead.pipeline_stage,
                                "days_stalled": days_stalled,
                                "deal_value": float(value),
                            }
                        )

            total_leads = max(len(leads), 1)
            stalled_ratio = len(stalled) / total_leads
            health_score = Decimal(str(round(max(0, 100 - (stalled_ratio * 100)), 2)))

            bottlenecks = sorted(stage_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            bottleneck_str = json.dumps([{"stage": s, "count": c} for s, c in bottlenecks])

            record = PipelineHealth(
                organization_id=organization_id,
                pipeline_health_score=health_score,
                revenue_at_risk=revenue_at_risk,
                stalled_deals_count=len(stalled),
                conversion_bottlenecks=bottleneck_str,
            )
            self.db.add(record)
            self.db.commit()

            if float(revenue_at_risk) >= settings.pulse_revenue_risk_threshold:
                webhook = org.slack_webhook_url or settings.slack_webhook_url
                if webhook:
                    asyncio.run(
                        self.slack.send_alert(
                            webhook,
                            f"⚠️ Revio AI Alert: ${revenue_at_risk:,.0f} revenue at risk for {org.company_name}",
                        )
                    )

            result = {
                "pipeline_health_score": float(health_score),
                "revenue_at_risk": float(revenue_at_risk),
                "stalled_deals_count": len(stalled),
                "stalled_deals": stalled[:20],
                "conversion_bottlenecks": bottlenecks,
            }
            run_logger.complete(result)
            return result
        except Exception as exc:
            run_logger.fail(str(exc))
            raise
