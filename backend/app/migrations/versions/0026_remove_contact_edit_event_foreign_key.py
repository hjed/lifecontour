"""remove contact_edit_event foreign key

Revision ID: 0026
Revises: 0025
Create Date: 2026-02-25 21:56:36.712498

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_constraint(
        "contact_edit_event_aggregate_id_fkey",
        "contact_edit_event",
        type_="foreignkey",
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.create_foreign_key(
        "contact_edit_event_aggregate_id_fkey",
        "contact_edit_event",
        "contacts",
        ["aggregate_id"],
        ["id"],
        ondelete="CASCADE",
    )
