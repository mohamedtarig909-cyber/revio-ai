"""Initial Revio AI schema

Revision ID: 001_initial
Revises:
Create Date: 2026-06-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("subscription_tier", sa.String(50), server_default="free"),
        sa.Column("stripe_customer_id", sa.String(255), unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), unique=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("agents_enabled", sa.Boolean(), server_default="true"),
        sa.Column("auto_send_enabled", sa.Boolean(), server_default="true"),
        sa.Column("slack_webhook_url", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False, server_default=""),
        sa.Column("subscription_status", sa.String(50), server_default="incomplete"),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_organization_id", "users", ["organization_id"])

    op.create_table(
        "crm_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("sync_status", sa.String(50), server_default="idle"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("portal_id", sa.String(255)),
        sa.Column("instance_url", sa.String(512)),
    )
    op.create_index("ix_crm_integrations_organization_id", "crm_integrations", ["organization_id"])

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crm_lead_id", sa.String(255)),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(50)),
        sa.Column("company", sa.String(255)),
        sa.Column("deal_value", sa.Numeric(15, 2)),
        sa.Column("pipeline_stage", sa.String(100)),
        sa.Column("lead_status", sa.String(50), server_default="active"),
        sa.Column("last_contact_date", sa.DateTime(timezone=True)),
        sa.Column("assigned_rep", sa.String(255)),
        sa.Column("notes", sa.Text()),
        sa.Column("priority_score", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_leads_organization_id", "leads", ["organization_id"])
    op.create_index("ix_leads_email", "leads", ["email"])
    op.create_index("ix_leads_lead_status", "leads", ["lead_status"])

    op.create_table(
        "lead_analysis",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recovery_probability", sa.Numeric(5, 4)),
        sa.Column("reason_lead_died", sa.Text()),
        sa.Column("confidence_score", sa.Numeric(5, 4)),
        sa.Column("recommended_strategy", sa.Text()),
        sa.Column("recommended_message", sa.Text()),
        sa.Column("buying_signals", sa.Text()),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lead_analysis_lead_id", "lead_analysis", ["lead_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("execution_time_ms", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("celery_task_id", sa.String(255)),
        sa.Column("metadata_json", sa.Text()),
    )
    op.create_index("ix_agent_runs_organization_id", "agent_runs", ["organization_id"])
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])

    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("subject_line", sa.String(500)),
        sa.Column("message_content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("external_message_id", sa.String(255)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_campaigns_organization_id", "campaigns", ["organization_id"])

    op.create_table(
        "daily_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_content", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("emailed_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "pipeline_health",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_health_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("revenue_at_risk", sa.Numeric(15, 2), server_default="0"),
        sa.Column("stalled_deals_count", sa.Integer(), server_default="0"),
        sa.Column("conversion_bottlenecks", sa.Text()),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pipeline_health")
    op.drop_table("daily_reports")
    op.drop_table("campaigns")
    op.drop_table("agent_runs")
    op.drop_table("lead_analysis")
    op.drop_table("leads")
    op.drop_table("crm_integrations")
    op.drop_table("users")
    op.drop_table("organizations")
