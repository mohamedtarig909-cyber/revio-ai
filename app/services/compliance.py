"""Suppression checks and unsubscribe tokens.

Every outbound send must call `is_suppressed` first. Tokens for the unsubscribe
link are stateless HMACs over (organization, channel, value) so a link stays
valid forever without storing anything, and cannot be forged to opt someone
else out of a different organization.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.suppression import Suppression

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize(channel: str, value: str) -> str:
    """Emails are case-insensitive; phone numbers compare on digits only."""
    v = (value or "").strip()
    if channel == "sms":
        digits = "".join(c for c in v if c.isdigit())
        return digits[-11:] if len(digits) > 11 else digits
    return v.lower()


def is_suppressed(db: Session, organization_id: UUID, channel: str, value: str) -> bool:
    """True if this address/number must not be contacted. Fails closed on error."""
    if not value:
        return True
    norm = normalize(channel, value)
    if not norm:
        return True
    try:
        row = db.execute(
            select(Suppression.id).where(
                Suppression.organization_id == organization_id,
                Suppression.value == norm,
                Suppression.channel.in_([channel, "all"]),
            ).limit(1)
        ).first()
        return row is not None
    except Exception:                                   # noqa: BLE001
        # If the check itself breaks we must not send. Silence is the safe failure.
        logger.exception("suppression check failed; blocking send to be safe")
        return True


def suppress(db: Session, organization_id: UUID, channel: str, value: str,
             reason: str = "unsubscribed", source: str = "") -> bool:
    """Add to the do-not-contact list. Idempotent; returns True if newly added."""
    norm = normalize(channel, value)
    if not norm:
        return False
    exists = db.execute(
        select(Suppression.id).where(
            Suppression.organization_id == organization_id,
            Suppression.channel == channel,
            Suppression.value == norm,
        ).limit(1)
    ).first()
    if exists:
        return False
    db.add(Suppression(organization_id=organization_id, channel=channel,
                       value=norm, reason=reason[:120], source=source[:120]))
    db.commit()
    logger.info("suppressed %s on %s for org %s (%s)", norm, channel, organization_id, reason)
    return True


# --------------------------------------------------------------------------
# Unsubscribe links
# --------------------------------------------------------------------------

def _sign(organization_id: str, channel: str, value: str) -> str:
    msg = f"{organization_id}|{channel}|{value}".encode()
    key = (settings.jwt_secret_key or "revio").encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]


def make_token(organization_id: UUID | str, channel: str, value: str) -> str:
    return _sign(str(organization_id), channel, normalize(channel, value))


def verify_token(organization_id: str, channel: str, value: str, token: str) -> bool:
    expected = _sign(str(organization_id), channel, normalize(channel, value))
    return hmac.compare_digest(expected, (token or "").strip())


def unsubscribe_url(base_url: str, organization_id: UUID | str,
                    channel: str, value: str) -> str:
    from urllib.parse import quote
    norm = normalize(channel, value)
    tok = make_token(organization_id, channel, norm)
    return (f"{base_url.rstrip('/')}/unsubscribe"
            f"?o={organization_id}&c={channel}&v={quote(norm)}&t={tok}")


# Appended to every outbound email. Plain, obvious, one click.
def email_footer(base_url: str, organization_id: UUID | str, email: str) -> str:
    url = unsubscribe_url(base_url, organization_id, "email", email)
    return (f'<hr style="border:none;border-top:1px solid #e5e5e5;margin:26px 0 12px"/>'
            f'<p style="font-size:12px;color:#888;line-height:1.5">'
            f'Do not want these emails? '
            f'<a href="{url}" style="color:#888">Unsubscribe</a>. '
            f'We honor every request immediately.</p>')
