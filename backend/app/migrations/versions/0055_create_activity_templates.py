"""create activity templates

Revision ID: 0055
Revises: 0054
Create Date: 2026-05-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- activity_templates table ---
    op.execute(
        """
        CREATE TABLE activity_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id VARCHAR(50) NOT NULL,
            name VARCHAR(200) NOT NULL,
            template_type VARCHAR(20) NOT NULL,
            region VARCHAR(200),
            description TEXT,
            -- Canyoning-specific columns
            french_grade VARCHAR(20),
            canyon_type VARCHAR(20),
            water_gauge_name VARCHAR(200),
            -- Caving-specific columns
            is_vertical BOOLEAN,
            is_horizontal BOOLEAN,
            -- Climbing-specific columns
            climbing_type VARCHAR(20),
            grade INTEGER,
            length INTEGER,
            -- Timestamps
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            -- Constraints
            CONSTRAINT ck_activity_templates_type
                CHECK (template_type IN ('canyoning', 'caving', 'climbing')),
            CONSTRAINT ck_activity_templates_canyoning_fields
                CHECK (template_type = 'canyoning' OR (french_grade IS NULL AND canyon_type IS NULL AND water_gauge_name IS NULL)),
            CONSTRAINT ck_activity_templates_caving_fields
                CHECK (template_type = 'caving' OR (is_vertical IS NULL AND is_horizontal IS NULL)),
            CONSTRAINT ck_activity_templates_climbing_fields
                CHECK (template_type = 'climbing' OR (climbing_type IS NULL AND grade IS NULL AND length IS NULL)),
            CONSTRAINT ck_activity_templates_canyon_type_values
                CHECK (canyon_type IS NULL OR canyon_type IN ('vertical', 'aquatic', 'mixed')),
            CONSTRAINT ck_activity_templates_climbing_type_values
                CHECK (climbing_type IS NULL OR climbing_type IN ('sport', 'trad', 'bouldering'))
        )
        """
    )

    # Indexes for activity_templates
    op.create_index("ix_activity_templates_user_id", "activity_templates", ["user_id"])
    op.create_index(
        "ix_activity_templates_user_type",
        "activity_templates",
        ["user_id", "template_type"],
    )

    # --- template_pitches table ---
    op.execute(
        """
        CREATE TABLE template_pitches (
            id SERIAL PRIMARY KEY,
            template_id UUID NOT NULL
                REFERENCES activity_templates(id) ON DELETE CASCADE,
            pitch_number INTEGER NOT NULL,
            height INTEGER,
            anchor_location VARCHAR(20),
            anchor_type VARCHAR(50),
            did_rescue BOOLEAN,
            did_setup BOOLEAN,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
            CONSTRAINT uq_template_pitches_template_pitch
                UNIQUE (template_id, pitch_number)
        )
        """
    )

    op.create_index(
        "ix_template_pitches_template_id", "template_pitches", ["template_id"]
    )

    # --- Add template_id FK to journal_canyoning_data ---
    op.add_column(
        "journal_canyoning_data",
        sa.Column("template_id", sa.dialects.postgresql.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_canyoning_data_template_id",
        "journal_canyoning_data",
        "activity_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove template_id FK from journal_canyoning_data
    op.drop_constraint(
        "fk_journal_canyoning_data_template_id",
        "journal_canyoning_data",
        type_="foreignkey",
    )
    op.drop_column("journal_canyoning_data", "template_id")

    # Drop template_pitches
    op.drop_index("ix_template_pitches_template_id", table_name="template_pitches")
    op.drop_table("template_pitches")

    # Drop activity_templates
    op.drop_index("ix_activity_templates_user_type", table_name="activity_templates")
    op.drop_index("ix_activity_templates_user_id", table_name="activity_templates")
    op.drop_table("activity_templates")
