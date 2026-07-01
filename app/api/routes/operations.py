from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.db.models.agent_run import AgentRun
from app.db.models.campaign import Campaign, CampaignChannel, CampaignStatus
from app.db.models.daily_report import DailyReport
from app.db.models.lead import Lead
from app.db.models.pipeline_health import PipelineHealth
from app.db.models.user import User
from app.db.session import get_db
from app.schemas import (
    AgentLogListResponse,
    AgentRunResponse,
    CampaignResponse,
    CampaignSendRequest,
    DailyReportResponse,
    PipelineHealthResponse,
)
from app.services.messaging.email_service import EmailService
from app.services.messaging.sms_service import SMSService

router = APIRouter(tags=["Campaigns", "Reports", "Pipeline", "Agents"])


@router.get("/campaigns", response_model=list[CampaignResponse])
@limiter.limit("60/minute")
async def list_campaigns(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    result = await db.execute(
        select(Campaign)
        .where(Campaign.organization_id == current_user.organization_id)
        .order_by(Campaign.sent_at.desc().nullslast())
        .limit(100)
    )
    return [CampaignResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/campaign/send", response_model=CampaignResponse)
@limiter.limit("30/minute")
async def send_campaign(
    request: Request,
    payload: CampaignSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    lead_result = await db.execute(
        select(Lead).where(Lead.id == payload.lead_id, Lead.organization_id == current_user.organization_id)
    )
    lead = lead_result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    campaign = Campaign(
        organization_id=current_user.organization_id,
        lead_id=lead.id,
        channel=payload.channel,
        subject_line=payload.subject_line,
        message_content=payload.message_content or "",
        status=CampaignStatus.SCHEDULED,
    )
    db.add(campaign)
    await db.flush()

    email_service = EmailService()
    sms_service = SMSService()

    try:
        if payload.channel == CampaignChannel.EMAIL:
            if not lead.email:
                raise HTTPException(status_code=400, detail="Lead has no email")
            msg_id = email_service.send_via_sendgrid(
                lead.email,
                payload.subject_line or "Following up",
                payload.message_content or "",
            )
        elif payload.channel in (CampaignChannel.SMS, CampaignChannel.WHATSAPP):
            if not lead.phone:
                raise HTTPException(status_code=400, detail="Lead has no phone")
            msg_id = sms_service.send_sms(lead.phone, payload.message_content or "")
        else:
            raise HTTPException(status_code=400, detail="Invalid channel")

        campaign.status = CampaignStatus.SENT
        campaign.sent_at = datetime.now(UTC)
        campaign.external_message_id = msg_id
    except Exception as exc:
        campaign.status = CampaignStatus.FAILED
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.get("/reports/daily", response_model=list[DailyReportResponse])
@limiter.limit("60/minute")
async def list_daily_reports(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.organization_id == current_user.organization_id)
        .order_by(DailyReport.generated_at.desc())
        .limit(limit)
    )
    return [DailyReportResponse.model_validate(r) for r in result.scalars().all()]


@router.get("/pipeline/health", response_model=PipelineHealthResponse)
@limiter.limit("60/minute")
async def get_pipeline_health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    result = await db.execute(
        select(PipelineHealth)
        .where(PipelineHealth.organization_id == current_user.organization_id)
        .order_by(PipelineHealth.generated_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="No pipeline health data yet")
    return PipelineHealthResponse.model_validate(record)


@router.get("/agent/logs", response_model=AgentLogListResponse)
@limiter.limit("60/minute")
async def get_agent_logs(
    request: Request,
    agent_name: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    stmt = select(AgentRun).where(AgentRun.organization_id == current_user.organization_id)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)

    from sqlalchemy import func

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(AgentRun.started_at.desc()).limit(limit))
    runs = result.scalars().all()

    return AgentLogListResponse(
        items=[AgentRunResponse.model_validate(r) for r in runs],
        total=total or 0,
    )
