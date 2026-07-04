"""
Customer authentication — register / login / me.

The backend previously had JWT verification but no way to *get* a token. These
endpoints let the website sign users up and in (email + password), returning a
JWT used as `Authorization: Bearer <token>` for the rest of /api/v1.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""
    company: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization_id: str
    email: str


# NOTE: slowapi's limiter broke Pydantic body parsing on these endpoints
# (body was demanded as a query param). Rate limiting to be re-added via
# middleware later; auth correctness comes first.
@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    email = body.email.strip().lower()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        if not existing.hashed_password:
            # Account was auto-provisioned by a Whop payment — claim it now.
            existing.hashed_password = hash_password(body.password)
            if body.name:
                existing.name = body.name
            await db.commit()
            return TokenOut(access_token=create_access_token(existing.id),
                            organization_id=str(existing.organization_id or ""),
                            email=existing.email)
        raise HTTPException(status_code=400, detail="Email already registered")

    org = Organization(
        company_name=body.company or f"{email.split('@')[0]} workspace",
        agents_enabled=True,
        auto_send_enabled=False,   # compliance: off by default
    )
    db.add(org)
    await db.flush()

    user = User(
        email=email,
        name=body.name or email.split("@")[0],
        hashed_password=hash_password(body.password),
        organization_id=org.id,
        subscription_status="trialing",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TokenOut(access_token=create_access_token(user.id),
                    organization_id=str(org.id), email=user.email)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email.strip().lower()))).scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id),
                    organization_id=str(user.organization_id or ""), email=user.email)


@router.get("/me")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, user.organization_id) if user.organization_id else None
    return {
        "id": str(user.id), "email": user.email, "name": user.name,
        "organization_id": str(user.organization_id or ""),
        "subscription_status": user.subscription_status,
        "company": org.company_name if org else None,
        "onboarded": bool(org and not org.company_name.endswith(" workspace")),
    }


class GoogleIn(BaseModel):
    credential: str    # Google ID token from Sign-In with Google


@router.get("/google/config")
async def google_config():
    """Frontend asks whether Google sign-in is configured (and with which client)."""
    from app.config import get_settings
    return {"client_id": get_settings().google_client_id or ""}


@router.post("/google")
async def google_signin(body: GoogleIn, db: AsyncSession = Depends(get_db)):
    """Verify a Google ID token, then sign the user in (creating the account +
    workspace on first Google login). Returns our JWT like normal login."""
    import httpx

    from app.config import get_settings
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(400, "Google sign-in is not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://oauth2.googleapis.com/tokeninfo",
                                 params={"id_token": body.credential})
    except httpx.HTTPError:
        raise HTTPException(503, "Could not reach Google")
    if r.status_code != 200:
        raise HTTPException(401, "Invalid Google token")
    info = r.json()
    if info.get("aud") != settings.google_client_id:
        raise HTTPException(401, "Google token was issued for a different app")
    email = (info.get("email") or "").strip().lower()
    if not email or info.get("email_verified") not in ("true", True):
        raise HTTPException(401, "Google account email not verified")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    created = False
    if user is None:
        org = Organization(company_name=f"{email.split('@')[0]} workspace",
                           agents_enabled=True, auto_send_enabled=False)
        db.add(org)
        await db.flush()
        user = User(email=email, name=info.get("name") or email.split("@")[0],
                    hashed_password="", organization_id=org.id,
                    subscription_status="trialing")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        created = True
    return {"access_token": create_access_token(user.id), "token_type": "bearer",
            "organization_id": str(user.organization_id or ""), "email": user.email,
            "created": created, "subscription_status": user.subscription_status}


class OnboardingIn(BaseModel):
    company: str


@router.post("/onboarding")
async def complete_onboarding(body: OnboardingIn,
                              user: User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Onboarding step: set the real company name on the user's organization."""
    if not user.organization_id:
        raise HTTPException(400, "No organization")
    org = await db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    name = body.company.strip()
    if not name:
        raise HTTPException(400, "Company name required")
    org.company_name = name[:255]
    await db.commit()
    return {"organization_id": str(org.id), "company": org.company_name}
