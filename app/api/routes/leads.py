from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rate_limit import limiter
from app.core.security import get_paid_user
from app.db.models.lead import Lead
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.user import User
from app.db.session import get_db
from app.schemas import LeadAnalysisResponse, LeadDetailResponse, LeadListResponse, LeadResponse

router = APIRouter(prefix="/leads", tags=["Leads"])


@router.get("", response_model=LeadListResponse)
@limiter.limit("120/minute")
async def list_leads(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_paid_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    org_id = current_user.organization_id
    base = select(Lead).where(Lead.organization_id == org_id)
    if status:
        base = base.where(Lead.lead_status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    offset = (page - 1) * page_size
    result = await db.execute(base.order_by(Lead.updated_at.desc()).offset(offset).limit(page_size))
    leads = result.scalars().all()

    return LeadListResponse(
        items=[LeadResponse.model_validate(l) for l in leads],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{lead_id}", response_model=LeadDetailResponse)
@limiter.limit("120/minute")
async def get_lead(
    request: Request,
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_paid_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    result = await db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.organization_id == current_user.organization_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    analysis_result = await db.execute(
        select(LeadAnalysis)
        .where(LeadAnalysis.lead_id == lead_id)
        .order_by(LeadAnalysis.analyzed_at.desc())
        .limit(1)
    )
    analysis = analysis_result.scalar_one_or_none()

    return LeadDetailResponse(
        **LeadResponse.model_validate(lead).model_dump(),
        notes=lead.notes,
        latest_analysis=LeadAnalysisResponse.model_validate(analysis) if analysis else None,
    )
