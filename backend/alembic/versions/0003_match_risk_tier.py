"""risk triage on matches

Supports routing a reviewer to the matches that carry genuine risk relevance
instead of an undifferentiated list. Tiers are produced deterministically by
`rules_engine.assess_risk_tier`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS risk_tier TEXT")
    op.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS risk_reason TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_matches_risk_tier ON matches (screening_id, risk_tier)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_matches_risk_tier")
    op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS risk_reason")
    op.execute("ALTER TABLE matches DROP COLUMN IF EXISTS risk_tier")
