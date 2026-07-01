import logging
import secrets
from datetime import UTC, datetime
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import hash_password
from app.db.models.organization import Organization, SubscriptionTier
from app.db.models.user import SubscriptionStatus, User
from app.services.messaging.email_service import EmailService

logger = logging.getLogger(__name__)
settings = get_settings()
stripe.api_key = settings.stripe_secret_key


class StripeBillingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.email_service = EmailService()

    def construct_event(self, payload: bytes, sig_header: str) -> stripe.Event:
        return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)

    async def handle_checkout_completed(self, session: dict) -> None:
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        customer_email = session.get("customer_details", {}).get("email") or session.get("customer_email")
        customer_name = session.get("customer_details", {}).get("name") or "User"
        company_name = session.get("metadata", {}).get("company_name") or "My Company"

        if not customer_email:
            logger.error("Checkout session missing email")
            return

        existing_user = self.db.execute(select(User).where(User.email == customer_email)).scalar_one_or_none()
        if existing_user:
            org = self.db.get(Organization, existing_user.organization_id) if existing_user.organization_id else None
            if org:
                org.stripe_customer_id = customer_id
                org.stripe_subscription_id = subscription_id
                org.agents_enabled = True
                existing_user.subscription_status = SubscriptionStatus.ACTIVE
                self.db.commit()
                return

        org = Organization(
            company_name=company_name,
            subscription_tier=SubscriptionTier.STARTER,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            agents_enabled=True,
        )
        self.db.add(org)
        self.db.flush()

        user = User(
            email=customer_email,
            name=customer_name,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            subscription_status=SubscriptionStatus.ACTIVE,
            organization_id=org.id,
        )
        self.db.add(user)
        org.owner_user_id = user.id
        self.db.commit()

        await self.email_service.send_welcome_email(customer_email, customer_name, company_name)
        logger.info("Created org %s and user %s from Stripe checkout", org.id, user.id)

    def handle_payment_succeeded(self, invoice: dict) -> None:
        customer_id = invoice.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return
        user = self.db.execute(
            select(User).where(User.organization_id == org.id)
        ).scalars().first()
        if user:
            user.subscription_status = SubscriptionStatus.ACTIVE
            org.agents_enabled = True
            self.db.commit()

    def handle_payment_failed(self, invoice: dict) -> None:
        customer_id = invoice.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return
        users = self.db.execute(select(User).where(User.organization_id == org.id)).scalars().all()
        for user in users:
            user.subscription_status = SubscriptionStatus.PAST_DUE
        self.db.commit()
        logger.warning("Payment failed for org %s", org.id)

    def handle_subscription_deleted(self, subscription: dict) -> None:
        customer_id = subscription.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return
        org.agents_enabled = False
        org.subscription_tier = SubscriptionTier.FREE
        org.stripe_subscription_id = None
        users = self.db.execute(select(User).where(User.organization_id == org.id)).scalars().all()
        for user in users:
            user.subscription_status = SubscriptionStatus.CANCELED
        self.db.commit()
        logger.info("Subscription canceled for org %s — agents disabled", org.id)

    def _get_org_by_customer(self, customer_id: str | None) -> Organization | None:
        if not customer_id:
            return None
        return self.db.execute(
            select(Organization).where(Organization.stripe_customer_id == customer_id)
        ).scalar_one_or_none()
