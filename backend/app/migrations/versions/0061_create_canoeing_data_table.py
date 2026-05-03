"""create canoeing data table

Revision ID: 0061
Revises: 0060
Create Date: 2026-05-03 14:12:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE journal_canoeing_data (
            journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
            water_type VARCHAR(100),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE journal_canoeing_data")
