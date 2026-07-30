"""Do-not-contact list.

Revision ID: 005_suppressions
Revises: 004_admin_analytics

IF NOT EXISTS throughout so a retry converges rather than failing halfway.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005_suppressions"
down_revision: Union[str, None] = "004_admin_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS suppressions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            channel         VARCHAR(20)  NOT NULL DEFAULT 'email',
            value           VARCHAR(320) NOT NULL,
            reason          VARCHAR(120) DEFAULT 'unsubscribed',
            source          VARCHAR(120) DEFAULT '',
            created_at      TIMESTAMPTZ  DEFAULT now(),
            updated_at      TIMESTAMPTZ  DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_suppressions_org ON suppressions (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_suppressions_value ON suppressions (value)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_suppression_org_channel_value
        ON suppressions (organization_id, channel, value)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_suppression_org_channel_value")
    op.execute("DROP INDEX IF EXISTS ix_suppressions_value")
    op.execute("DROP INDEX IF EXISTS ix_suppressions_org")
    op.execute("DROP TABLE IF EXISTS suppressions")
