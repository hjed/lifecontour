"""remove_activity_type_add_abseil_pitches

Revision ID: 0051
Revises: 0050
Create Date: 2026-04-29 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove activity_type, add abseil_pitches table, add aggregate fields.

    1. Drop activity_type column from journal_outdoor_activity_data
    2. Add number_of_setups and number_of_rescues to journal_abseiling_data
    3. Create abseil_pitches table with FK to journal_abseiling_data
    """
    op.execute(
        """
        -- 1. Drop activity_type from outdoor activity data
        ALTER TABLE journal_outdoor_activity_data
        DROP COLUMN IF EXISTS activity_type;

        -- 2. Add aggregate fields to abseiling data
        ALTER TABLE journal_abseiling_data
        ADD COLUMN number_of_setups INTEGER;

        ALTER TABLE journal_abseiling_data
        ADD COLUMN number_of_rescues INTEGER;

        -- 3. Create abseil_pitches table
        CREATE TABLE abseil_pitches (
            id SERIAL PRIMARY KEY,
            journal_id INTEGER NOT NULL
                REFERENCES journal_abseiling_data(journal_id) ON DELETE CASCADE,
            pitch_number INTEGER NOT NULL,
            height INTEGER,
            anchor_location VARCHAR(20),
            anchor_type VARCHAR(50),
            did_rescue BOOLEAN,
            did_setup BOOLEAN,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            UNIQUE (journal_id, pitch_number)
        );

        CREATE INDEX idx_abseil_pitches_journal_id ON abseil_pitches(journal_id);
        """
    )


def downgrade() -> None:
    """Reverse: drop abseil_pitches, remove aggregate fields, re-add activity_type."""
    op.execute(
        """
        -- Drop abseil_pitches table
        DROP TABLE IF EXISTS abseil_pitches;

        -- Remove aggregate fields from abseiling data
        ALTER TABLE journal_abseiling_data
        DROP COLUMN IF EXISTS number_of_setups;

        ALTER TABLE journal_abseiling_data
        DROP COLUMN IF EXISTS number_of_rescues;

        -- Re-add activity_type to outdoor activity data
        ALTER TABLE journal_outdoor_activity_data
        ADD COLUMN activity_type VARCHAR(100);
        """
    )
