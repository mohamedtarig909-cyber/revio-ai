"""
Intelligence layer DB migration.

Creates:
  - execution_plans
  - strategy_outcomes
  - strategy_patterns
  - conversation_sessions
  - historical_cases (with pgvector embedding column)

Run:
  alembic upgrade head

Requires pgvector extension installed in Supabase (available by default).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_intelligence_layer"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector (safe to run even if already enabled)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # execution_plans
    # ------------------------------------------------------------------
    op.create_table(
        "execution_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_lead", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("primary_channel", sa.String(32), nullable=False, server_default="email"),
        sa.Column("delay_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("human_escalation", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("offer_discount", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sequence", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("reasoning_iterations", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tools_called", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("retrieved_case_ids", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("raw_planner_output", postgresql.JSON(), nullable=True),
        sa.Column("executed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_execution_plans_org_lead", "execution_plans", ["organization_id", "lead_id"])
    op.create_index("ix_execution_plans_lead_id", "execution_plans", ["lead_id"])
    op.create_index("ix_execution_plans_created_at", "execution_plans", ["created_at"])

    # ------------------------------------------------------------------
    # strategy_outcomes
    # ------------------------------------------------------------------
    op.create_table(
        "strategy_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("lead_type", sa.String(64), nullable=True),
        sa.Column("deal_value", sa.Float(), nullable=True),
        sa.Column("objection_type", sa.String(64), nullable=True),
        sa.Column("strategy_used", sa.String(128), nullable=True),
        sa.Column("channel_used", sa.String(32), nullable=False, server_default="email"),
        sa.Column("sequence_used", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("discount_offered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("human_escalated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("response_received", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deal_recovered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revenue_closed", sa.Float(), nullable=True),
        sa.Column("time_to_response_hours", sa.Float(), nullable=True),
        sa.Column("total_messages_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversation_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_strategy_outcomes_org_id", "strategy_outcomes", ["organization_id"])
    op.create_index("ix_strategy_outcomes_lead_id", "strategy_outcomes", ["lead_id"])
    op.create_index("ix_strategy_outcomes_industry", "strategy_outcomes", ["industry"])
    op.create_index("ix_strategy_outcomes_objection", "strategy_outcomes", ["objection_type"])
    op.create_index(
        "ix_strategy_outcomes_industry_channel",
        "strategy_outcomes",
        ["industry", "channel_used"],
    )
    op.create_index(
        "ix_strategy_outcomes_org_created",
        "strategy_outcomes",
        ["organization_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # strategy_patterns
    # ------------------------------------------------------------------
    op.create_table(
        "strategy_patterns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("pattern_type", sa.String(32), nullable=False),
        sa.Column("pattern_key", sa.String(256), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recommended_strategy", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "last_computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_strategy_patterns",
        "strategy_patterns",
        ["organization_id", "industry", "pattern_type", "pattern_key"],
    )
    op.create_index("ix_strategy_patterns_industry", "strategy_patterns", ["industry"])
    op.create_index("ix_strategy_patterns_type", "strategy_patterns", ["pattern_type"])
    op.create_index("ix_strategy_patterns_org", "strategy_patterns", ["organization_id"])

    # ------------------------------------------------------------------
    # conversation_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_history", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("current_stage", sa.String(64), nullable=False, server_default="initial"),
        sa.Column("objection_history", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("detected_intents", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "conversation_status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("human_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_rep_id", sa.String(128), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_conversation_sessions_org", "conversation_sessions", ["organization_id"])
    op.create_index("ix_conversation_sessions_lead", "conversation_sessions", ["lead_id"])
    op.create_index(
        "ix_conversation_sessions_lead_status",
        "conversation_sessions",
        ["lead_id", "conversation_status"],
    )
    op.create_index(
        "ix_conversation_sessions_org_updated",
        "conversation_sessions",
        ["organization_id", "updated_at"],
    )

    # ------------------------------------------------------------------
    # historical_cases (with pgvector column)
    # ------------------------------------------------------------------
    op.create_table(
        "historical_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_outcome_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("industry", sa.String(128), nullable=True),
        sa.Column("deal_value", sa.Float(), nullable=True),
        sa.Column("primary_objection", sa.String(64), nullable=True),
        sa.Column("channel_used", sa.String(32), nullable=True),
        sa.Column("outcome_positive", sa.Boolean(), nullable=True),
        sa.Column("revenue_recovered", sa.Float(), nullable=True),
        sa.Column("case_summary", sa.Text(), nullable=False),
        sa.Column("winning_strategy", postgresql.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_historical_cases_org", "historical_cases", ["organization_id"])
    op.create_index("ix_historical_cases_industry", "historical_cases", ["industry"])
    op.create_index(
        "ix_historical_cases_org_industry",
        "historical_cases",
        ["organization_id", "industry"],
    )

    # Add pgvector column (vector(1536) for text-embedding-3-small)
    op.execute("ALTER TABLE historical_cases ADD COLUMN embedding vector(1536)")

    # HNSW index for fast approximate nearest-neighbour search
    op.execute(
        """
        CREATE INDEX ix_historical_cases_embedding_hnsw
        ON historical_cases
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_historical_cases_embedding_hnsw")
    op.drop_table("historical_cases")
    op.drop_table("conversation_sessions")
    op.drop_table("strategy_patterns")
    op.drop_table("strategy_outcomes")
    op.drop_table("execution_plans")
