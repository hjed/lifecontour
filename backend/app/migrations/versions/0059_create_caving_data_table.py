"""create caving data table

Revision ID: 0059
Revises: 0058
Create Date: 2026-05-02 18:51:12.066777

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE journal_caving_data (
            journal_id INTEGER PRIMARY KEY REFERENCES journals(id) ON DELETE CASCADE,
            template_id UUID REFERENCES activity_templates(id) ON DELETE SET NULL,
            is_vertical BOOLEAN,
            is_horizontal BOOLEAN,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE journal_caving_data")
