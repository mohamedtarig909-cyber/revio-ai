from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class LeadAnalysis(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "lead_analysis"

    lead_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    recovery_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reason_lead_died: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    recommended_strategy: Mapped[str | None] = mapped_column(Text)
    recommended_message: Mapped[str | None] = mapped_column(Text)
    buying_signals: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lead: Mapped["Lead"] = relationship(back_populates="analyses")
