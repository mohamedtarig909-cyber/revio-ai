from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LeadStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"
    REACTIVATED = "reactivated"
    LOST = "lost"
    ESCALATED = "escalated"


class Lead(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "leads"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    crm_lead_id: Mapped[str | None] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    company: Mapped[str | None] = mapped_column(String(255))
    deal_value: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    pipeline_stage: Mapped[str | None] = mapped_column(String(100))
    lead_status: Mapped[str] = mapped_column(String(50), default=LeadStatus.ACTIVE, index=True)
    last_contact_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_rep: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    priority_score: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="leads")
    analyses: Mapped[list["LeadAnalysis"]] = relationship(back_populates="lead")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="lead")
