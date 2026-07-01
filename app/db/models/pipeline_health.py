from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class PipelineHealth(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "pipeline_health"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    pipeline_health_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    revenue_at_risk: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    stalled_deals_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_bottlenecks: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped["Organization"] = relationship(back_populates="pipeline_health_records")
