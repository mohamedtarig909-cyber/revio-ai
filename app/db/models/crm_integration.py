from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class CRMProvider(StrEnum):
    HUBSPOT = "hubspot"
    SALESFORCE = "salesforce"
    CSV = "csv"


class SyncStatus(StrEnum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"


class CRMIntegration(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "crm_integrations"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(50), default=SyncStatus.IDLE)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    portal_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instance_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="crm_integrations")
