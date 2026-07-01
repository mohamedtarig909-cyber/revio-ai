"""
Phase 2 autonomous intelligence models.
Adds to the existing intelligence.py models — do NOT remove those.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CycleStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ESCALATED = "escalated"
    EXHAUSTED = "exhausted"


class OverrideTrigger(str, enum.Enum):
    FUNDING_EVENT = "funding_event"
    JOB_CHANGE = "job_change"
    HIRING_SPIKE = "hiring_spike"
    EXECUTIVE_CHANGE = "executive_change"
    PRODUCT_LAUNCH = "product_launch"
    COMPETITIVE_MOVEMENT = "competitive_movement"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# strategy_cycles
# ---------------------------------------------------------------------------

class StrategyCycle(Base):
    __tablename__ = "strategy_cycles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    current_strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channels_exhausted: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    strategies_tried: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    success_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    next_action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(CycleStatus), nullable=False, default=CycleStatus.PENDING, index=True
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    confidence_floor: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    execution_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_strategy_cycles_org_lead_status", "organization_id", "lead_id", "status"),
    )


# ---------------------------------------------------------------------------
# lead_world_state
# ---------------------------------------------------------------------------

class LeadWorldState(Base):
    __tablename__ = "lead_world_state"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Status
    current_status: Mapped[str] = mapped_column(String(64), nullable=False, default="cold")
    objection_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_channel_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    days_since_last_response: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deal_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_strategy_used: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # External signals
    funding_event_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    funding_event_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    job_change_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    job_change_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    hiring_spike_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executive_change_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Computed scores
    urgency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Objection signals
    pricing_objection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    budget_objection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timing_objection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    competitor_objection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trust_objection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Conversation intelligence
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_messages_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Escalation
    human_intervention_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Meta
    override_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_trigger: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_scout_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("lead_id", "organization_id", name="uq_lead_world_state"),
        Index("ix_lead_world_state_org_urgency", "organization_id", "urgency_score"),
        Index("ix_lead_world_state_override", "organization_id", "override_active"),
    )


# ---------------------------------------------------------------------------
# strategy_experiments
# ---------------------------------------------------------------------------

class StrategyExperiment(Base):
    __tablename__ = "strategy_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    experiment_name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Variants
    strategy_a: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    strategy_b: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    strategy_c: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Results
    leads_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leads_b: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leads_c: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_rate_a: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_rate_b: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_rate_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conversion_rate_a: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conversion_rate_b: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conversion_rate_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    revenue_a: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    revenue_b: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    revenue_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Conclusion
    winning_strategy: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "a", "b", "c"
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_concluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_strategy_experiments_industry_concluded", "industry", "is_concluded"),
    )


# ---------------------------------------------------------------------------
# strategy_scores  (RL weight table)
# ---------------------------------------------------------------------------

class StrategyScore(Base):
    __tablename__ = "strategy_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    strategy_key: Mapped[str] = mapped_column(String(256), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deal_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Running stats
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    ema_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # Exponential moving avg
    revenue_per_attempt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "industry", "strategy_key",
            name="uq_strategy_scores"
        ),
        Index("ix_strategy_scores_weighted", "organization_id", "weighted_score"),
    )


# ---------------------------------------------------------------------------
# override_events
# ---------------------------------------------------------------------------

class OverrideEvent(Base):
    __tablename__ = "override_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(Enum(OverrideTrigger), nullable=False)
    trigger_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    previous_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    new_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    urgency_score_before: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    urgency_score_after: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# revenue_forensics
# ---------------------------------------------------------------------------

class RevenueForensics(Base):
    __tablename__ = "revenue_forensics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Pipeline analysis
    monthly_revenue_leakage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    largest_conversion_bottleneck: Mapped[str | None] = mapped_column(String(128), nullable=True)
    average_response_time_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    worst_pipeline_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    highest_risk_deals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # Detailed breakdowns
    revenue_by_stage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revenue_by_channel: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    objection_kill_rates: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rep_performance: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    channel_performance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ignored_opportunities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # Recommendations
    recommended_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    executive_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    leakage_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0-100

    # Raw LLM analysis
    raw_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_revenue_forensics_org_generated", "organization_id", "generated_at"),
    )


# ---------------------------------------------------------------------------
# experiment_assignments
# ---------------------------------------------------------------------------

class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group: Mapped[str] = mapped_column(String(8), nullable=False)  # "a", "b", "c"
    responded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    converted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revenue: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("experiment_id", "lead_id", name="uq_experiment_assignment"),
    )
