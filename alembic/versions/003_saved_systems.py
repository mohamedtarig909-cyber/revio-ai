"""Saved systems — builder specs claimed into workspaces.

Revision ID: 003_saved_systems
Revises: 001_intelligence_layer
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_saved_systems"
down_revision: Union[str, None] = "001_intelligence_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_systems",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("industry", sa.String(120), server_default=""),
        sa.Column("goal", sa.String(120), server_default=""),
        sa.Column("spec", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("saved_systems")
