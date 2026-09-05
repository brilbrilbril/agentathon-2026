"""dccs_search_results.entity_name nullable

Some DCCS history rows are redacted ('***** CONFIDENTIAL *****') and genuinely
carry no entity name in the source PDF — pad with NULL rather than fabricate.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dccs_search_results ALTER COLUMN entity_name DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE dccs_search_results ALTER COLUMN entity_name SET NOT NULL")
