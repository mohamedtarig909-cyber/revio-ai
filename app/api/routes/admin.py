"""
Admin / testing control panel API.

Protected by a single ADMIN_TOKEN (sent as the `X-Admin-Token` header) so the
operator can drive the whole system by hand:
  - bootstrap an organization + admin user and mint a JWT
  - seed sample dormant leads
  - toggle agents_enabled / auto_send_enabled
  - manually trigger the REVIVE agent and the full orchestrator pipeline
  - read an overview snapshot

Uses the SYNC session because the agents are synchronous. Endpoints are plain
`def` so FastAPI runs them in a threadpool (agents call asyncio.run internally).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select

from app.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.db.session import SyncSessionLocal
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.agent_run import AgentRun
from app.db.models.page_view import PageView
from app.db.models.saved_system import SavedSystem
from app.agents.revive_agent import ReviveAgent
from app.orchestrator.engine import OrchestratorEngine

settings = get_settings()
router = APIRouter(prefix="/admin", tags=["Admin"])

SAMPLE_LEADS = [
    {"name": "Jane Cooper", "company": "Acme Roofing", "domain": "acme.test", "value": 12000,
     "notes": "Requested a quote, went quiet after the proposal. No follow-up."},
    {"name": "Marcus Reid", "company": "Sunline Solar", "domain": "sunline.test", "value": 21000,
     "notes": "Interested but said timing wasn't right; never re-contacted."},
    {"name": "Priya Nair", "company": "Harbor Insurance", "domain": "harbor.test", "value": 8400,
     "notes": "Pricing objection at proposal stage."},
    {"name": "Devon Blake", "company": "Metro Mortgage", "domain": "metro.test", "value": 16000,
     "notes": "Compared us to a competitor and stalled."},
    {"name": "Ana Torres", "company": "GreenHome Services", "domain": "greenhome.test", "value": 5000,
     "notes": "Booked a demo, no-showed, never followed up."},
]


def _admin_user_from_bearer(authorization: str) -> User | None:
    """Resolve a signed-in owner from a normal Bearer JWT, or None."""
    if not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    except Exception:                                   # noqa: BLE001
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    with SyncSessionLocal() as db:
        try:
            user = db.get(User, UUID(str(sub)))
        except Exception:                               # noqa: BLE001
            return None
        if not user:
            return None
        owner = (settings.owner_email or "").strip().lower()
        if user.is_admin or (owner and (user.email or "").strip().lower() == owner):
            return user
    return None


def require_admin(x_admin_token: str = Header(default=""),
                  authorization: str = Header(default="")) -> None:
    """Owner gate. Accepts an email+password session (preferred) or the legacy token."""
    if _admin_user_from_bearer(authorization):
        return
    if settings.admin_token and x_admin_token == settings.admin_token:
        return
    raise HTTPException(status_code=401, detail="Sign in with your owner account to continue")


@router.get("/me")
def admin_me(authorization: str = Header(default=""),
             x_admin_token: str = Header(default="")):
    """Who am I, and am I allowed in? Used by the dashboard right after sign-in."""
    user = _admin_user_from_bearer(authorization)
    if user:
        return {"is_admin": True, "email": user.email, "name": user.name,
                "via": "account"}
    if settings.admin_token and x_admin_token == settings.admin_token:
        return {"is_admin": True, "email": "", "name": "Operator", "via": "token"}
    raise HTTPException(status_code=403,
                        detail="This account is not the owner account")


@router.post("/bootstrap")
def bootstrap(email: str = Query("admin@revio.ai"),
              company: str = Query("Test Company"),
              _: None = Depends(require_admin)):
    """Create (or reuse) an org + admin user and return a JWT for the main API."""
    with SyncSessionLocal() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user and user.organization_id:
            org = db.get(Organization, user.organization_id)
        else:
            org = Organization(company_name=company, agents_enabled=True, auto_send_enabled=False)
            db.add(org)
            db.flush()
            if user is None:
                user = User(email=email, name="Admin",
                            hashed_password=hash_password("change-me"),
                            organization_id=org.id, subscription_status="active")
                db.add(user)
            else:
                user.organization_id = org.id
            db.flush()
        db.commit()
        token = create_access_token(user.id)
        return {
            "organization_id": str(org.id),
            "user_id": str(user.id),
            "email": user.email,
            "access_token": token,
            "usage": "Send as 'Authorization: Bearer <access_token>' to /api/v1/* endpoints.",
        }


@router.get("/users")
def list_users(_: None = Depends(require_admin)):
    """Owner view: every user, their org, subscription status, and lead count."""
    with SyncSessionLocal() as db:
        users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
        out = []
        for u in users:
            org = db.get(Organization, u.organization_id) if u.organization_id else None
            leads = db.scalar(select(func.count()).select_from(Lead).where(
                Lead.organization_id == u.organization_id)) if u.organization_id else 0
            out.append({
                "id": str(u.id), "email": u.email, "name": u.name,
                "subscription_status": u.subscription_status,
                "organization_id": str(u.organization_id or ""),
                "company": org.company_name if org else None,
                "tier": getattr(org, "subscription_tier", None) if org else None,
                "leads": leads or 0,
                "claimed": bool(u.hashed_password),
                "created_at": str(u.created_at),
            })
        active = sum(1 for x in out if x["subscription_status"] == "active")
        return {"users": out, "total": len(out), "active_subscriptions": active}


@router.post("/impersonate")
def impersonate(user_id: UUID, _: None = Depends(require_admin)):
    """Mint a login token for any user — open the app exactly as they see it."""
    with SyncSessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        return {"access_token": create_access_token(user.id),
                "email": user.email,
                "note": "Set localStorage.revio_token to this value on the site origin."}


@router.post("/user/{user_id}/subscription")
def set_subscription(user_id: UUID, status: str = Query(...),
                     _: None = Depends(require_admin)):
    """Manually activate/cancel a user's subscription (active|trialing|canceled)."""
    if status not in ("active", "trialing", "past_due", "canceled", "incomplete"):
        raise HTTPException(400, "Invalid status")
    with SyncSessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        user.subscription_status = status
        db.commit()
        return {"id": str(user.id), "email": user.email, "subscription_status": status}


@router.delete("/user/{user_id}")
def delete_user(user_id: UUID, _: None = Depends(require_admin)):
    """Ban/delete an account (their org + data cascade per FK rules)."""
    with SyncSessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        email = user.email
        db.delete(user)
        db.commit()
        return {"deleted": email}


@router.get("/orgs")
def list_orgs(_: None = Depends(require_admin)):
    with SyncSessionLocal() as db:
        orgs = db.execute(select(Organization)).scalars().all()
        out = []
        for o in orgs:
            leads = db.scalar(
                select(func.count()).select_from(Lead).where(Lead.organization_id == o.id)
            )
            out.append({
                "id": str(o.id), "company_name": o.company_name,
                "agents_enabled": o.agents_enabled, "auto_send_enabled": o.auto_send_enabled,
                "leads": leads or 0,
            })
        return {"organizations": out}


@router.post("/org/{org_id}/settings")
def update_settings(org_id: UUID,
                    agents_enabled: bool | None = None,
                    auto_send_enabled: bool | None = None,
                    _: None = Depends(require_admin)):
    with SyncSessionLocal() as db:
        org = db.get(Organization, org_id)
        if not org:
            raise HTTPException(404, "Organization not found")
        if agents_enabled is not None:
            org.agents_enabled = agents_enabled
        if auto_send_enabled is not None:
            org.auto_send_enabled = auto_send_enabled
        db.commit()
        return {"id": str(org.id), "agents_enabled": org.agents_enabled,
                "auto_send_enabled": org.auto_send_enabled}


@router.post("/seed-leads")
def seed_leads(org_id: UUID, count: int = Query(5, ge=1, le=50),
               _: None = Depends(require_admin)):
    """Insert sample dormant leads so REVIVE has something to work on."""
    with SyncSessionLocal() as db:
        org = db.get(Organization, org_id)
        if not org:
            raise HTTPException(404, "Organization not found")
        cold = datetime.now(UTC) - timedelta(days=120)
        created = 0
        for i in range(count):
            s = SAMPLE_LEADS[i % len(SAMPLE_LEADS)]
            db.add(Lead(
                organization_id=org.id, full_name=s["name"],
                email=f"lead{i}@{s['domain']}", company=s["company"],
                deal_value=Decimal(str(s["value"])), pipeline_stage="proposal",
                lead_status=LeadStatus.DORMANT, last_contact_date=cold, notes=s["notes"],
            ))
            created += 1
        db.commit()
        return {"seeded": created, "org_id": str(org_id)}


@router.post("/run/revive")
def run_revive(org_id: UUID, _: None = Depends(require_admin)):
    """Trigger the REVIVE agent now (scores dormant leads)."""
    with SyncSessionLocal() as db:
        return ReviveAgent(db).run(org_id)


@router.post("/run/pipeline")
def run_pipeline(org_id: UUID, _: None = Depends(require_admin)):
    """Trigger the full orchestrator: CRM sync → REVIVE → MESSAGE → (EXECUTION if auto-send)."""
    with SyncSessionLocal() as db:
        return OrchestratorEngine(db).run_full_pipeline(org_id)


@router.get("/overview")
def overview(org_id: UUID, _: None = Depends(require_admin)):
    with SyncSessionLocal() as db:
        leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.organization_id == org_id))
        dormant = db.scalar(select(func.count()).select_from(Lead).where(
            Lead.organization_id == org_id, Lead.lead_status == LeadStatus.DORMANT))
        analyses = db.scalar(
            select(func.count()).select_from(LeadAnalysis)
            .join(Lead, LeadAnalysis.lead_id == Lead.id)
            .where(Lead.organization_id == org_id))
        runs = db.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.organization_id == org_id))
        recent = db.execute(
            select(AgentRun).where(AgentRun.organization_id == org_id)
            .order_by(AgentRun.started_at.desc()).limit(10)).scalars().all()
        return {
            "leads": leads or 0, "dormant": dormant or 0, "analyses": analyses or 0,
            "agent_runs": runs or 0,
            "recent_runs": [{
                "agent": str(getattr(r, "agent_name", "")),
                "status": str(getattr(r, "status", "")),
                "started_at": str(getattr(r, "started_at", "")),
            } for r in recent],
        }


@router.get("/analytics")
def analytics(days: int = Query(30, ge=1, le=365), _: None = Depends(require_admin)):
    """Everything happening in the business, in one payload.

    Traffic, signups, paying customers and systems built — headline numbers plus
    a daily series so the dashboard can draw trends without a second round-trip.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    with SyncSessionLocal() as db:
        # ---- headline numbers ----
        views = db.scalar(select(func.count()).select_from(PageView)
                          .where(PageView.created_at >= since)) or 0
        visitors = db.scalar(
            select(func.count(func.distinct(PageView.visitor_id)))
            .where(PageView.created_at >= since, PageView.visitor_id != "")) or 0
        signups = db.scalar(select(func.count()).select_from(User)
                            .where(User.created_at >= since)) or 0
        total_users = db.scalar(select(func.count()).select_from(User)) or 0
        paying = db.scalar(select(func.count()).select_from(User)
                           .where(User.subscription_status == "active")) or 0
        systems = db.scalar(select(func.count()).select_from(SavedSystem)) or 0
        leads_total = db.scalar(select(func.count()).select_from(Lead)) or 0

        # ---- daily series (views / visitors / signups) ----
        day = func.date_trunc("day", PageView.created_at)
        vrows = db.execute(
            select(day.label("d"), func.count().label("v"),
                   func.count(func.distinct(PageView.visitor_id)).label("u"))
            .where(PageView.created_at >= since).group_by("d").order_by("d")).all()
        sday = func.date_trunc("day", User.created_at)
        srows = db.execute(
            select(sday.label("d"), func.count().label("s"))
            .where(User.created_at >= since).group_by("d").order_by("d")).all()
        vmap = {str(r.d)[:10]: (int(r.v), int(r.u)) for r in vrows}
        smap = {str(r.d)[:10]: int(r.s) for r in srows}
        series = []
        start = (datetime.now(UTC) - timedelta(days=days - 1)).date()
        for i in range(days):
            key = str(start + timedelta(days=i))
            v, u = vmap.get(key, (0, 0))
            series.append({"day": key, "views": v, "visitors": u,
                           "signups": smap.get(key, 0)})

        # ---- where the traffic goes ----
        top_pages = [
            {"path": str(r.path), "views": int(r.c)}
            for r in db.execute(
                select(PageView.path, func.count().label("c"))
                .where(PageView.created_at >= since)
                .group_by(PageView.path).order_by(func.count().desc()).limit(12)).all()
        ]
        top_refs = [
            {"referrer": str(r.referrer or "direct"), "views": int(r.c)}
            for r in db.execute(
                select(PageView.referrer, func.count().label("c"))
                .where(PageView.created_at >= since)
                .group_by(PageView.referrer).order_by(func.count().desc()).limit(8)).all()
        ]

        # ---- who just showed up ----
        recent_users = db.execute(
            select(User).order_by(User.created_at.desc()).limit(8)).scalars().all()
        recent_systems = db.execute(
            select(SavedSystem).order_by(SavedSystem.created_at.desc()).limit(8)).scalars().all()

    return {
        "range_days": days,
        "kpis": {
            "page_views": views, "unique_visitors": visitors, "signups": signups,
            "total_users": total_users, "paying_customers": paying,
            "systems_built": systems, "total_leads": leads_total,
        },
        "funnel": {
            "visitors": visitors, "signups": signups, "paying": paying,
            "visitor_to_signup": round(signups / visitors * 100, 1) if visitors else 0.0,
            "signup_to_paying": round(paying / total_users * 100, 1) if total_users else 0.0,
        },
        "series": series,
        "top_pages": top_pages,
        "top_referrers": top_refs,
        "recent_signups": [{
            "email": u.email, "name": u.name,
            "status": u.subscription_status,
            "created_at": str(u.created_at),
        } for u in recent_users],
        "recent_systems": [{
            "industry": s.industry, "goal": s.goal, "created_at": str(s.created_at),
        } for s in recent_systems],
    }
