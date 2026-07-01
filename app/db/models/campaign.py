from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class CampaignChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RESPONDED = "responded"
    BOUNCED = "bounced"


class Campaign(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "campaigns"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_line: Mapped[str | None] = mapped_column(String(500))
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=CampaignStatus.DRAFT, index=True)
    external_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship(back_populates="campaigns")
    lead: Mapped["Lead"] = relationship(back_populates="campaigns")
