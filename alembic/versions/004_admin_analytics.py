"""Owner dashboard — admin flag on users + first-party page-view tracking.

Revision ID: 004_admin_analytics
Revises: 003_saved_systems

Written with IF NOT EXISTS throughout: the User model now expects `is_admin`, so
a half-applied migration would break every user query (and therefore login).
Making each step re-runnable means a retry always converges instead of failing.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004_admin_analytics"
down_revision: Union[str, None] = "003_saved_systems"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS page_views (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            path         VARCHAR(300) DEFAULT '/',
            referrer     VARCHAR(300) DEFAULT '',
            visitor_id   VARCHAR(64)  DEFAULT '',
            country      VARCHAR(80)  DEFAULT '',
            created_at   TIMESTAMPTZ  DEFAULT now(),
            updated_at   TIMESTAMPTZ  DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_page_views_path ON page_views (path)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_page_views_visitor_id ON page_views (visitor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_page_views_created_at ON page_views (created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_page_views_created_at")
    op.execute("DROP INDEX IF EXISTS ix_page_views_visitor_id")
    op.execute("DROP INDEX IF EXISTS ix_page_views_path")
    op.execute("DROP TABLE IF EXISTS page_views")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin")
