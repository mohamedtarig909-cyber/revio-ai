"""Do-not-contact list.

One row per address or phone number that must never be contacted again for a
given organization. This is the legal backbone of outbound: CAN-SPAM and TCPA
both require that an opt-out is honored permanently and promptly, so every send
is checked against this table first.

Rows are written from three places: the unsubscribe link in every message, the
ResponseAgent when a reply says "stop"/"unsubscribe", and manual entry by the
operator. Nothing ever deletes a suppression automatically.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Suppression(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint("organization_id", "channel", "value",
                         name="uq_suppression_org_channel_value"),
    )

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    # "email" | "sms" | "all"
    channel: Mapped[str] = mapped_column(String(20), default="email", nullable=False)
    # normalized email address or phone number
    value: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    # unsubscribed | complaint | bounce | manual
    reason: Mapped[str] = mapped_column(String(120), default="unsubscribed")
    # unsubscribe_link | reply_keyword | admin | import
    source: Mapped[str] = mapped_column(String(120), default="")
