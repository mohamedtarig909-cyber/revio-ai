"""
Customer authentication — register / login / me.

The backend previously had JWT verification but no way to *get* a token. These
endpoints let the website sign users up and in (email + password), returning a
JWT used as `Authorization: Bearer <token>` for the rest of /api/v1.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
async def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id), "email": user.email, "name": user.name,
        "organization_id": str(user.organization_id or ""),
        "subscription_status": user.subscription_status,
    }
