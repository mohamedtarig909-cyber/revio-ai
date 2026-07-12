from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SavedSystem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A system spec generated in the public builder, claimed into a workspace."""

    __tablename__ = "saved_systems"

    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    industry: Mapped[str] = mapped_column(String(120), default="")
    goal: Mapped[str] = mapped_column(String(120), default="")
    spec: Mapped[dict] = mapped_column(JSONB, default=dict)
