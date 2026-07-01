"""
Intelligence layer models for Revio AI autonomous reasoning system.
Extends existing models — do NOT remove existing model files.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ChannelType(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    HUMAN = "human"


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    ESCALATED = "escalated"
    PENDING = "pending"


class IntentType(str, enum.Enum):
    PRICE_OBJECTION = "price_objection"
    BUDGET_OBJECTION = "budget_objection"
    TIMING_OBJECTION = "timing_objection"
    APPROVAL_NEEDED = "approval_needed"
    COMPETITOR_OBJECTION = "competitor_objection"
    INTEREST_SIGNAL = "interest_signal"
    MEETING_REQUEST = "meeting_request"
    UNCLEAR = "unclear"
    POSITIVE = "positive"
    NEGATIVE = "negative"


class PatternType(str, enum.Enum):
    CHANNEL = "channel"
    OBJECTION = "objection"
    DEAL_SIZE = "deal_size"
    INDUSTRY = "industry"
    TIMING = "timing"


# ---------------------------------------------------------------------------
# execution_plans
# ---------------------------------------------------------------------------

class ExecutionPlan(Base):
    __tablename__ = "execution_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Decision fields
    contact_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    primary_channel: Mapped[str] = mapped_column(
        Enum(ChannelType), nullable=False, default=ChannelType.EMAIL
    )
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_escalation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    offer_discount: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Iteration tracking
    reasoning_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tools_called: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    retrieved_case_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    raw_planner_output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)

    # Lifecycle
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_execution_plans_org_lead", "organization_id", "lead_id"),
        Index("ix_execution_plans_created_at", "created_at"),
    )


# ---------------------------------------------------------------------------
# strategy_outcomes
# ---------------------------------------------------------------------------

class StrategyOutcome(Base):
    __tablename__ = "strategy_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    execution_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Lead / deal context
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lead_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    objection_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Strategy used
    strategy_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel_used: Mapped[str] = mapped_column(
        Enum(ChannelType), nullable=False, default=ChannelType.EMAIL
    )
    sequence_used: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    discount_offered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Outcomes
    response_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deal_recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revenue_closed: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to_response_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversation_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_strategy_outcomes_industry_channel", "industry", "channel_used"),
        Index("ix_strategy_outcomes_org_created", "organization_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# strategy_patterns
# ---------------------------------------------------------------------------

class StrategyPattern(Base):
    __tablename__ = "strategy_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )  # NULL = global pattern

    # Pattern identifiers
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pattern_type: Mapped[str] = mapped_column(
        Enum(PatternType), nullable=False, index=True
    )
    pattern_key: Mapped[str] = mapped_column(String(256), nullable=False)

    # Learned stats
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommended_strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Aggregation metadata
    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_strategy_patterns_unique",
            "organization_id",
            "industry",
            "pattern_type",
            "pattern_key",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# conversation_sessions
# ---------------------------------------------------------------------------

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    execution_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Conversation state
    message_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="initial")
    objection_history: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    detected_intents: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    conversation_status: Mapped[str] = mapped_column(
        Enum(ConversationStatus), nullable=False, default=ConversationStatus.ACTIVE
    )

    # Escalation tracking
    human_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_rep_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Timestamps
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_conversation_sessions_lead_status", "lead_id", "conversation_status"),
        Index("ix_conversation_sessions_org_updated", "organization_id", "updated_at"),
    )


# ---------------------------------------------------------------------------
# historical_cases  (pgvector)
# ---------------------------------------------------------------------------

class HistoricalCase(Base):
    """
    Stores embedded lead context for semantic retrieval via pgvector.
    The `embedding` column is a vector(1536) — created via raw DDL migration,
    not mapped here to avoid SQLAlchemy vector type dependency.
    """
    __tablename__ = "historical_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    strategy_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Context stored as text for embedding source
    context_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured metadata for retrieval filtering
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    deal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_objection: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome_positive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    revenue_recovered: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Summary injected into LLM context
    case_summary: Mapped[str] = mapped_column(Text, nullable=False)
    winning_strategy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_historical_cases_org_industry", "organization_id", "industry"),
    )
