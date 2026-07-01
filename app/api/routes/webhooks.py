import hashlib
import hmac
import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.config import get_settings
from app.db.models.crm_integration import CRMIntegration, CRMProvider
from app.db.session import SyncSessionLocal
from app.orchestrator.engine import OrchestratorEngine
from app.services.billing.stripe_service import StripeBillingService
from app.services.crm.crm_service import CRMSyncService

logger = logging.getLogger(__name__)
settings = get_settings()

stripe_router = APIRouter(prefix="/stripe", tags=["Stripe Webhooks"])
crm_webhook_router = APIRouter(prefix="/crm/webhooks", tags=["CRM Webhooks"])


@stripe_router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    db = SyncSessionLocal()
    try:
        billing = StripeBillingService(db)
        event = billing.construct_event(payload, sig_header)

        if event["type"] == "checkout.session.completed":
            await billing.handle_checkout_completed(event["data"]["object"])
        elif event["type"] == "invoice.payment_succeeded":
            billing.handle_payment_succeeded(event["data"]["object"])
        elif event["type"] == "invoice.payment_failed":
            billing.handle_payment_failed(event["data"]["object"])
        elif event["type"] == "customer.subscription.deleted":
            billing.handle_subscription_deleted(event["data"]["object"])
        else:
            logger.info("Unhandled Stripe event: %s", event["type"])

        return {"received": True}
    except Exception as exc:
        logger.exception("Stripe webhook error")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()


def _verify_hubspot_signature(body: bytes, signature: str) -> bool:
    if not settings.hubspot_webhook_secret:
        return True
    expected = hmac.new(
        settings.hubspot_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@crm_webhook_router.post("/hubspot")
async def hubspot_webhook(
    request: Request,
    x_hubspot_signature: str | None = Header(default=None),
):
    body = await request.body()
    if x_hubspot_signature and not _verify_hubspot_signature(body, x_hubspot_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    events = await request.json()
    if not isinstance(events, list):
        events = [events]

    db = SyncSessionLocal()
    orchestrator = OrchestratorEngine(db)
    crm_service = CRMSyncService(db)

    try:
        for event in events:
            portal_id = str(event.get("portalId", ""))
            integration = db.execute(
                select(CRMIntegration).where(
                    CRMIntegration.provider == CRMProvider.HUBSPOT,
                    CRMIntegration.portal_id == portal_id,
                )
            ).scalar_one_or_none()

            if not integration:
                logger.warning("No integration for HubSpot portal %s", portal_id)
                continue

            org_id = integration.organization_id
            event_type = event.get("subscriptionType", "")

            if event_type in ("contact.creation", "contact.propertyChange", "deal.propertyChange"):
                crm_service.upsert_lead_from_webhook(org_id, event)
                orchestrator.schedule_reanalysis(org_id)
            elif event_type == "deal.deletion":
                logger.info("Deal deleted event for org %s", org_id)

        db.commit()
        return {"processed": len(events)}
    finally:
        db.close()
