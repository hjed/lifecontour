"""add contact methods unique constraints

Revision ID: 0025
Revises: 0024
Create Date: 2026-02-25 21:38:58.670937

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Ensure a contact only has one primary method of each type
    op.create_index(
        "ix_contact_methods_primary_unique",
        "contact_methods",
        ["contact_id", "method_type"],
        unique=True,
        postgresql_where=sa.text("is_primary = true"),
    )

    # Ensure email addresses are explicitly unique system-wide
    op.create_index(
        "ix_contact_methods_email_unique",
        "contact_methods",
        ["value"],
        unique=True,
        postgresql_where=sa.text("method_type = 'email'"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_contact_methods_email_unique", table_name="contact_methods")
    op.drop_index("ix_contact_methods_primary_unique", table_name="contact_methods")
