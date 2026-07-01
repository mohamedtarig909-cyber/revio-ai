import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.db.models.user import User
from app.db.session import SyncSessionLocal, get_db
from app.schemas import CSVUploadResponse, OAuthCallbackRequest
from app.services.crm.oauth_service import HubSpotOAuthService, SalesforceOAuthService
from app.services.ingest.csv_service import CSVImportService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm", tags=["CRM"])


@router.get("/hubspot/oauth")
@limiter.limit("30/minute")
async def hubspot_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")
    url = HubSpotOAuthService().get_authorization_url(current_user.organization_id)
    return {"authorization_url": url}


@router.get("/hubspot/oauth/callback")
async def hubspot_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    db = SyncSessionLocal()
    try:
        integration = await HubSpotOAuthService().handle_callback(db, code, UUID(state))
        return {"status": "connected", "provider": integration.provider, "integration_id": str(integration.id)}
    finally:
        db.close()


@router.post("/hubspot/oauth")
@limiter.limit("30/minute")
async def hubspot_oauth_exchange(
    request: Request,
    payload: OAuthCallbackRequest,
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    db = SyncSessionLocal()
    try:
        org_id = UUID(payload.state) if payload.state else current_user.organization_id
        integration = await HubSpotOAuthService().handle_callback(db, payload.code, org_id)
        return {"status": "connected", "integration_id": str(integration.id)}
    finally:
        db.close()


@router.get("/salesforce/oauth")
@limiter.limit("30/minute")
async def salesforce_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")
    url = SalesforceOAuthService().get_authorization_url(current_user.organization_id)
    return {"authorization_url": url}


@router.get("/salesforce/oauth/callback")
async def salesforce_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    db = SyncSessionLocal()
    try:
        integration = await SalesforceOAuthService().handle_callback(db, code, UUID(state))
        return {"status": "connected", "provider": integration.provider, "integration_id": str(integration.id)}
    finally:
        db.close()


@router.post("/salesforce/oauth")
@limiter.limit("30/minute")
async def salesforce_oauth_exchange(
    request: Request,
    payload: OAuthCallbackRequest,
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    db = SyncSessionLocal()
    try:
        org_id = UUID(payload.state) if payload.state else current_user.organization_id
        integration = await SalesforceOAuthService().handle_callback(db, payload.code, org_id)
        return {"status": "connected", "integration_id": str(integration.id)}
    finally:
        db.close()
