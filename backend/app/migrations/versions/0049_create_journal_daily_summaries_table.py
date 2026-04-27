"""create_journal_daily_summaries_table

Revision ID: 0049
Revises: 0048
Create Date: 2026-04-27 19:57:22.772096

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create journal_daily_summaries table."""
    op.execute(
        """
        CREATE TABLE journal_daily_summaries (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) NOT NULL,
            summary_date DATE NOT NULL,
            summary_text TEXT,
            journal_count INTEGER NOT NULL DEFAULT 0,
            event_count INTEGER NOT NULL DEFAULT 0,
            contact_count INTEGER NOT NULL DEFAULT 0,
            mood_average NUMERIC(3,1),
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            generated_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_journal_daily_summaries_user_date
                UNIQUE (user_id, summary_date),
            CONSTRAINT ck_journal_daily_summaries_status CHECK (
                status IN ('pending', 'generating', 'generated', 'failed', 'disabled')
            )
        );
        CREATE INDEX idx_journal_daily_summaries_user_date
            ON journal_daily_summaries (user_id, summary_date);
        """
    )


def downgrade() -> None:
    """Drop journal_daily_summaries table."""
    op.execute("DROP TABLE IF EXISTS journal_daily_summaries;")
