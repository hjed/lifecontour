"""add_contact_important_dates

Revision ID: 464c57448693
Revises: 0043
Create Date: 2026-04-11 19:38:15.954581

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Global configuration table for custom date types
    op.execute(
        """
        CREATE TABLE custom_date_types (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE contact_important_dates (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            date_type VARCHAR(30) NOT NULL,
            precision VARCHAR(10) NOT NULL,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            custom_date_type_id INTEGER REFERENCES custom_date_types(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (date_type IN ('birthday', 'marriage_anniversary', 'work_anniversary', 'first_met', 'custom')),
            CHECK (precision IN ('full', 'day_month', 'year')),
            CHECK (month IS NULL OR (month >= 1 AND month <= 12)),
            CHECK (day IS NULL OR (day >= 1 AND day <= 31)),
            -- Precision consistency checks
            CHECK (precision != 'full' OR (year IS NOT NULL AND month IS NOT NULL AND day IS NOT NULL)),
            CHECK (precision != 'day_month' OR (year IS NULL AND month IS NOT NULL AND day IS NOT NULL)),
            CHECK (precision != 'year' OR (year IS NOT NULL AND month IS NULL AND day IS NULL)),
            -- Custom label rule
            CHECK (date_type != 'custom' OR custom_date_type_id IS NOT NULL),
            CHECK (date_type = 'custom' OR custom_date_type_id IS NULL)
        );
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_contact_birthday ON contact_important_dates(contact_id) WHERE date_type = 'birthday';
        CREATE INDEX idx_contact_important_dates_contact_id ON contact_important_dates(contact_id);
        CREATE INDEX idx_contact_important_dates_type ON contact_important_dates(date_type);
        """
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.execute("DROP TABLE IF EXISTS contact_important_dates;")
    op.execute("DROP TABLE IF EXISTS custom_date_types;")
