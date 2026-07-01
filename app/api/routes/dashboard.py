import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.db.models.campaign import Campaign, CampaignStatus
from app.db.models.daily_report import DailyReport
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.pipeline_health import PipelineHealth
from app.db.models.user import User
from app.db.session import get_db
from app.schemas import (
    CampaignResponse,
    CampaignSendRequest,
    DailyReportResponse,
    DashboardOverviewResponse,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    PipelineHealthResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
@limiter.limit("60/minute")
async def get_dashboard_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="User not associated with an organization")

    org_id = current_user.organization_id
    since = datetime.now(UTC) - timedelta(hours=24)

    total_leads = await db.scalar(select(func.count()).select_from(Lead).where(Lead.organization_id == org_id))
    dormant = await db.scalar(
        select(func.count()).select_from(Lead).where(Lead.organization_id == org_id, Lead.lead_status == LeadStatus.DORMANT)
    )
    reactivated = await db.scalar(
        select(func.count()).select_from(Lead).where(Lead.organization_id == org_id, Lead.lead_status == LeadStatus.REACTIVATED)
    )

    pipeline = await db.execute(
        select(PipelineHealth)
        .where(PipelineHealth.organization_id == org_id)
        .order_by(PipelineHealth.generated_at.desc())
        .limit(1)
    )
    latest_pipeline = pipeline.scalar_one_or_none()

    campaigns_sent = await db.scalar(
        select(func.count()).select_from(Campaign).where(
            Campaign.organization_id == org_id, Campaign.sent_at >= since
        )
    )
    responses = await db.scalar(
        select(func.count()).select_from(Campaign).where(
            Campaign.organization_id == org_id, Campaign.responded_at >= since
        )
    )

    report_result = await db.execute(
        select(DailyReport)
        .where(DailyReport.organization_id == org_id)
        .order_by(DailyReport.generated_at.desc())
        .limit(1)
    )
    latest_report = report_result.scalar_one_or_none()

    return DashboardOverviewResponse(
        total_leads=total_leads or 0,
        dormant_leads=dormant or 0,
        reactivated_leads=reactivated or 0,
        revenue_at_risk=latest_pipeline.revenue_at_risk if latest_pipeline else Decimal("0"),
        pipeline_health_score=latest_pipeline.pipeline_health_score if latest_pipeline else None,
        campaigns_sent_24h=campaigns_sent or 0,
        responses_24h=responses or 0,
        latest_report=DailyReportResponse.model_validate(latest_report) if latest_report else None,
    )
