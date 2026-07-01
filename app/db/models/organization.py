from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionTier(StrEnum):
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"
    FREE = "free"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_tier: Mapped[str] = mapped_column(String(50), default=SubscriptionTier.FREE)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    owner_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agents_enabled: Mapped[bool] = mapped_column(default=True)
    auto_send_enabled: Mapped[bool] = mapped_column(default=True)
    slack_webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    users: Mapped[list["User"]] = relationship(
        "User", back_populates="organization", foreign_keys="User.organization_id"
    )
    crm_integrations: Mapped[list["CRMIntegration"]] = relationship(back_populates="organization")
    leads: Mapped[list["Lead"]] = relationship(back_populates="organization")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="organization")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="organization")
    daily_reports: Mapped[list["DailyReport"]] = relationship(back_populates="organization")
    pipeline_health_records: Mapped[list["PipelineHealth"]] = relationship(
        back_populates="organization"
    )
