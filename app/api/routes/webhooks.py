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
whop_router = APIRouter(prefix="/whop", tags=["Whop Webhooks"])

_WHOP_GRANT = {"membership.went_valid", "membership_went_valid", "membership.created",
               "payment.succeeded", "payment_succeeded"}
_WHOP_REVOKE = {"membership.went_invalid", "membership_went_invalid",
                "membership.cancelled", "membership.expired"}


def _verify_whop(headers, body: bytes) -> bool:
    """Accept either signing style:
    A) x-whop-signature: sha256=<hex hmac of raw body>
    B) Standard Webhooks (Svix-style): webhook-id / webhook-timestamp /
       webhook-signature: "v1,<base64>" over "id.timestamp.body", secret
       optionally prefixed "whsec_" (base64-encoded key).
    """
    import base64

    secret = (settings.whop_webhook_secret or "").strip()
    if not secret:
        return True   # not configured (dev) — accept

    # --- Scheme A: hex HMAC of the raw body ---
    sig_a = (headers.get("x-whop-signature") or headers.get("whop-signature")
             or headers.get("x-whop-webhook-signature") or "")
    if sig_a:
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        got = sig_a.split(",")[-1].replace("sha256=", "").strip()
        if got and hmac.compare_digest(expected, got):
            return True

    # --- Scheme B: Standard Webhooks ---
    msg_id = headers.get("webhook-id") or headers.get("svix-id") or ""
    ts = headers.get("webhook-timestamp") or headers.get("svix-timestamp") or ""
    sig_b = headers.get("webhook-signature") or headers.get("svix-signature") or ""
    if msg_id and ts and sig_b:
        keys: list[bytes] = [secret.encode()]
        if secret.startswith("whsec_"):
            try:
                keys.insert(0, base64.b64decode(secret[6:] + "=" * (-len(secret[6:]) % 4)))
            except Exception:  # noqa: BLE001
                pass
        signed = f"{msg_id}.{ts}.".encode() + body
        for key in keys:
            expected_b = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
            for part in sig_b.split(" "):
                cand = part.split(",", 1)[-1].strip()
                if cand and hmac.compare_digest(expected_b, cand):
                    return True

    # Diagnostics: header names only + signature previews (no secrets).
    logger.warning("[whop] signature mismatch. headers=%s sigA=%r sigB=%r id=%r ts=%r",
                   sorted(headers.keys()), sig_a[:24], sig_b[:32], msg_id[:20], ts[:20])
    return False


@whop_router.post("/webhook")
async def whop_webhook(request: Request):
    """Whop payment → automatic provisioning.

    On a valid membership/payment: activate the user with that email, creating
    the account + organization if they haven't registered yet (they later
    'claim' it by signing up with the same email — see /auth/register).
    """
    import json as _json

    from app.db.models.organization import Organization
    from app.db.models.user import User

    body = await request.body()
    if not _verify_whop(request.headers, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event = _json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    etype = str(event.get("action") or event.get("type") or "")
    data = event.get("data") or event
    email = (data.get("email") or data.get("user_email")
             or (data.get("user") or {}).get("email") or "").strip().lower()
    if not email:
        logger.warning("Whop webhook %s without an email; ignoring", etype)
        return {"received": True, "provisioned": False}

    granted = etype in _WHOP_GRANT
    revoked = etype in _WHOP_REVOKE
    if not (granted or revoked):
        return {"received": True, "provisioned": False, "event": etype}

    db = SyncSessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if granted:
            if user is None:
                org = Organization(company_name=f"{email.split('@')[0]} workspace",
                                   agents_enabled=True, auto_send_enabled=False)
                db.add(org)
                db.flush()
                user = User(email=email, name=email.split("@")[0],
                            hashed_password="",             # claimed at first sign-up
                            organization_id=org.id,
                            subscription_status="active")
                db.add(user)
            else:
                user.subscription_status = "active"
            logger.info("Whop: activated %s (%s)", email, etype)
        else:
            if user is not None:
                user.subscription_status = "canceled"
                logger.info("Whop: revoked %s (%s)", email, etype)
        db.commit()
        return {"received": True, "provisioned": granted, "revoked": revoked}
    finally:
        db.close()


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
