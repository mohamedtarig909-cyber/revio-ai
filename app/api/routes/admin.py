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
from app.core.security import create_access_token, hash_password
from app.db.session import SyncSessionLocal
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.lead import Lead, LeadStatus
from app.db.models.lead_analysis import LeadAnalysis
from app.db.models.agent_run import AgentRun
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


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")


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
