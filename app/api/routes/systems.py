"""Saved systems — claim the spec built in the public builder into the
user's workspace, and fetch it back for the dashboard greeting."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.models.saved_system import SavedSystem
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/systems", tags=["Systems"])


class ClaimIn(BaseModel):
    spec: dict = Field(default_factory=dict)
    industry: str = ""
    goal: str = ""


@router.post("/claim")
async def claim_system(body: ClaimIn, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """Save the visitor-built system into the signed-in user's workspace."""
    if not user.organization_id:
        raise HTTPException(400, "No organization")
    if not body.spec:
        raise HTTPException(400, "No system spec provided")
    row = SavedSystem(organization_id=user.organization_id,
                      industry=body.industry[:120], goal=body.goal[:120],
                      spec=body.spec)
    db.add(row)
    await db.commit()
    return {"claimed": True, "system_id": str(row.id)}


@router.get("/mine")
async def my_system(user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    """Latest system saved to this workspace (None if none claimed yet)."""
    if not user.organization_id:
        return {"system": None}
    row = (await db.execute(
        select(SavedSystem)
        .where(SavedSystem.organization_id == user.organization_id)
        .order_by(SavedSystem.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not row:
        return {"system": None}
    return {"system": {"id": str(row.id), "industry": row.industry,
                       "goal": row.goal, "spec": row.spec,
                       "created_at": str(row.created_at)}}
