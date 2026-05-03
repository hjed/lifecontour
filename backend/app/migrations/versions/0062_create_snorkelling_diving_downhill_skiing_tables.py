"""create snorkelling diving downhill skiing tables

Revision ID: c385507821a1
Revises: 0061
Create Date: 2026-05-03 18:24:47.478568

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c385507821a1"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute(
        """
        CREATE TABLE journal_snorkelling_data (
            journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE journal_diving_data (
            journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE journal_downhill_skiing_data (
            journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        );
        """
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.execute("DROP TABLE IF EXISTS journal_downhill_skiing_data;")
    op.execute("DROP TABLE IF EXISTS journal_diving_data;")
    op.execute("DROP TABLE IF EXISTS journal_snorkelling_data;")
