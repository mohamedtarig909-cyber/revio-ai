from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin


class AgentName(StrEnum):
    REVIVE = "revive"
    PULSE = "pulse"
    SCOUT = "scout"
    MESSAGE = "message"
    EXECUTION = "execution"
    RESPONSE = "response"
    REPORT = "report"
    ORCHESTRATOR = "orchestrator"
    CRM_SYNC = "crm_sync"


class AgentRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class AgentRun(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "agent_runs"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=AgentRunStatus.PENDING, index=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)

    organization: Mapped["Organization"] = relationship(back_populates="agent_runs")
