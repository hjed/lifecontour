"""normalize contact method email uniqueness

Revision ID: 0027
Revises: 0026
Create Date: 2026-03-08 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.drop_index("ix_contact_methods_email_unique", table_name="contact_methods")
    op.execute(
        """
        CREATE UNIQUE INDEX ix_contact_methods_email_unique
        ON contact_methods (LOWER(BTRIM(value)))
        WHERE method_type = 'email'
        """
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_contact_methods_email_unique", table_name="contact_methods")
    op.execute(
        """
        CREATE UNIQUE INDEX ix_contact_methods_email_unique
        ON contact_methods (value)
        WHERE method_type = 'email'
        """
    )
