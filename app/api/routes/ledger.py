"""Recovered-revenue ledger and pipeline watch.

These two endpoints exist to fight churn. A dead-lead sweep is finite: the big
win lands in month one and the pile is empty by month two, so customers stop
*seeing* value long before the product stops *delivering* it. The ledger keeps
the cumulative win visible, and the watch reframes the product from a one-time
excavation into something that never finishes: catching leads before they die.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models.campaign import Campaign
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/ledger", tags=["Ledger"])

# A lead is "going cold" before it is dormant. These are the windows the watch
# uses to catch it while the conversation is still warm enough to recover.
COOLING_DAYS = 14
CRITICAL_DAYS = 25


@router.get("")
async def ledger(user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    """Cumulative recovered revenue, month by month, plus what the system learned."""
    org = user.organization_id
    if not org:
        return {"recovered_total": 0, "recovered_this_month": 0, "jobs_recovered": 0,
                "series": [], "patterns_learned": 0, "since": None}

    val = func.coalesce(func.sum(cast(Lead.deal_value, Numeric)), 0)

    total = await db.scalar(
        select(val).where(Lead.organization_id == org,
                          Lead.lead_status == LeadStatus.REACTIVATED))
    jobs = await db.scalar(
        select(func.count()).select_from(Lead)
        .where(Lead.organization_id == org, Lead.lead_status == LeadStatus.REACTIVATED))

    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = await db.scalar(
        select(val).where(Lead.organization_id == org,
                          Lead.lead_status == LeadStatus.REACTIVATED,
                          Lead.updated_at >= month_start))

    # 12-month recovery curve
    since = datetime.now(UTC) - timedelta(days=365)
    month = func.date_trunc("month", Lead.updated_at)
    rows = (await db.execute(
        select(month.label("m"), val.label("v"), func.count().label("n"))
        .where(Lead.organization_id == org,
               Lead.lead_status == LeadStatus.REACTIVATED,
               Lead.updated_at >= since)
        .group_by("m").order_by("m"))).all()

    first = await db.scalar(
        select(func.min(Lead.created_at)).where(Lead.organization_id == org))

    # Everything the system has worked out about this business. This is the
    # number that makes leaving expensive.
    patterns = await db.scalar(
        select(func.count()).select_from(LeadAnalysis)
        .join(Lead, LeadAnalysis.lead_id == Lead.id)
        .where(Lead.organization_id == org))

    return {
        "recovered_total": float(total or 0),
        "recovered_this_month": float(this_month or 0),
        "jobs_recovered": int(jobs or 0),
        "patterns_learned": int(patterns or 0),
        "since": str(first) if first else None,
        "series": [{"month": str(r.m)[:7], "value": float(r.v or 0), "jobs": int(r.n)}
                   for r in rows],
    }


@router.get("/watch")
async def pipeline_watch(user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Leads going quiet right now — the work that never finishes.

    This is the answer to "I already worked my dead list". Every week more
    conversations drift, and catching them at day 14 is far cheaper than
    reviving them at day 90.
    """
    org = user.organization_id
    if not org:
        return {"cooling": 0, "critical": 0, "at_risk_value": 0, "items": []}

    now = datetime.now(UTC)
    cooling_at = now - timedelta(days=COOLING_DAYS)
    critical_at = now - timedelta(days=CRITICAL_DAYS)

    base = (Lead.organization_id == org, Lead.lead_status == LeadStatus.ACTIVE)

    cooling = await db.scalar(
        select(func.count()).select_from(Lead)
        .where(*base, Lead.last_contact_date < cooling_at,
               Lead.last_contact_date >= critical_at))
    critical = await db.scalar(
        select(func.count()).select_from(Lead)
        .where(*base, Lead.last_contact_date < critical_at))
    at_risk = await db.scalar(
        select(func.coalesce(func.sum(cast(Lead.deal_value, Numeric)), 0))
        .where(*base, Lead.last_contact_date < cooling_at))

    rows = (await db.execute(
        select(Lead).where(*base, Lead.last_contact_date < cooling_at)
        .order_by(Lead.deal_value.desc().nullslast()).limit(12))).scalars().all()

    items = []
    for l in rows:
        days = (now - l.last_contact_date).days if l.last_contact_date else 0
        items.append({
            "id": str(l.id), "name": l.full_name, "company": l.company,
            "value": float(l.deal_value or 0), "days_quiet": days,
            "state": "critical" if days >= CRITICAL_DAYS else "cooling",
        })

    return {"cooling": int(cooling or 0), "critical": int(critical or 0),
            "at_risk_value": float(at_risk or 0),
            "cooling_days": COOLING_DAYS, "critical_days": CRITICAL_DAYS,
            "items": items}
