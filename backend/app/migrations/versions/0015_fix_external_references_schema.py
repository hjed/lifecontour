"""Fix external_references table schema to match core_shared model

Revision ID: 0015
Revises: 0014
Create Date: 2026-01-30 18:30:00.000000

This migration fixes the schema mismatch between the external_references table
and the core_shared.models.external_reference.ExternalReference model.

Changes:
- Rename entity_id -> internal_entity_id
- Rename entity_type -> internal_entity_type
- Rename integration_source -> external_system
- Rename external_id -> external_entity_id
- Add external_entity_type column
- Replace external_url and metadata with reference_data
- Update indexes to use new column names
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix external_references table schema to match the model."""
    # Step 1: Drop old indexes (they reference old column names)
    op.drop_index("idx_external_references_entity", table_name="external_references")
    op.drop_index(
        "idx_external_references_integration_external", table_name="external_references"
    )
    op.drop_index(
        "idx_external_references_entity_type", table_name="external_references"
    )

    # Step 2: Drop old check constraints
    op.drop_constraint(
        "ck_external_references_entity_type",
        "external_references",
        type_="check",
    )
    op.drop_constraint(
        "ck_external_references_integration_source",
        "external_references",
        type_="check",
    )

    # Step 3: Rename columns
    op.alter_column(
        "external_references",
        "entity_id",
        new_column_name="internal_entity_id",
    )
    op.alter_column(
        "external_references",
        "entity_type",
        new_column_name="internal_entity_type",
    )
    op.alter_column(
        "external_references",
        "integration_source",
        new_column_name="external_system",
    )
    op.alter_column(
        "external_references",
        "external_id",
        new_column_name="external_entity_id",
    )

    # Step 4: Add new columns
    # Add external_entity_type - for existing rows, derive from internal_entity_type
    # We'll use a default value and then update it based on the entity type
    op.add_column(
        "external_references",
        sa.Column(
            "external_entity_type",
            sa.String(length=50),
            nullable=True,  # Temporarily nullable
        ),
    )

    # Update existing rows with sensible defaults based on internal_entity_type
    # For contacts -> person, for photos -> photo, etc.
    op.execute(
        """
        UPDATE external_references
        SET external_entity_type = CASE
            WHEN internal_entity_type = 'contact' THEN 'person'
            WHEN internal_entity_type = 'photo' THEN 'photo'
            WHEN internal_entity_type = 'album' THEN 'album'
            WHEN internal_entity_type = 'activity' THEN 'activity'
            WHEN internal_entity_type = 'journal_entry' THEN 'entry'
            WHEN internal_entity_type = 'calendar_event' THEN 'event'
            WHEN internal_entity_type = 'transaction' THEN 'transaction'
            ELSE 'unknown'
        END
        WHERE external_entity_type IS NULL
        """
    )

    # Now make it NOT NULL
    op.alter_column(
        "external_references",
        "external_entity_type",
        nullable=False,
    )

    # Add reference_data column (replaces external_url and metadata)
    op.add_column(
        "external_references",
        sa.Column("reference_data", sa.Text(), nullable=True),
    )

    # Migrate data from external_url and metadata to reference_data as JSON
    # This combines both fields into a single JSON field
    op.execute(
        """
        UPDATE external_references
        SET reference_data = json_build_object(
            'external_url', external_url,
            'metadata', metadata
        )::text
        WHERE external_url IS NOT NULL OR metadata IS NOT NULL
        """
    )

    # Step 5: Drop old columns
    op.drop_column("external_references", "external_url")
    op.drop_column("external_references", "metadata")

    # Step 6: Create new indexes with correct column names
    op.create_index(
        "ix_external_references_internal_lookup",
        "external_references",
        ["internal_entity_type", "internal_entity_id"],
    )
    op.create_index(
        "ix_external_references_external_lookup",
        "external_references",
        ["external_system", "external_entity_type", "external_entity_id"],
    )
    op.create_index(
        "ix_external_references_system_lookup",
        "external_references",
        ["external_system"],
    )


def downgrade() -> None:
    """Revert external_references table schema changes."""
    # Step 1: Drop new indexes
    op.drop_index(
        "ix_external_references_system_lookup", table_name="external_references"
    )
    op.drop_index(
        "ix_external_references_external_lookup", table_name="external_references"
    )
    op.drop_index(
        "ix_external_references_internal_lookup", table_name="external_references"
    )

    # Step 2: Add back old columns
    op.add_column(
        "external_references",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.add_column(
        "external_references",
        sa.Column("external_url", sa.TEXT(), nullable=True),
    )

    # Step 3: Migrate data back from reference_data to external_url and metadata
    op.execute(
        """
        UPDATE external_references
        SET
            external_url = (reference_data::json->>'external_url'),
            metadata = (reference_data::json->'metadata')
        WHERE reference_data IS NOT NULL
        """
    )

    # Step 4: Drop new columns
    op.drop_column("external_references", "reference_data")
    op.drop_column("external_references", "external_entity_type")

    # Step 5: Rename columns back
    op.alter_column(
        "external_references",
        "external_entity_id",
        new_column_name="external_id",
    )
    op.alter_column(
        "external_references",
        "external_system",
        new_column_name="integration_source",
    )
    op.alter_column(
        "external_references",
        "internal_entity_type",
        new_column_name="entity_type",
    )
    op.alter_column(
        "external_references",
        "internal_entity_id",
        new_column_name="entity_id",
    )

    # Step 6: Recreate old indexes
    op.create_index(
        "idx_external_references_entity_type",
        "external_references",
        ["entity_type"],
    )
    op.create_index(
        "idx_external_references_integration_external",
        "external_references",
        ["integration_source", "external_id"],
        unique=True,
    )
    op.create_index(
        "idx_external_references_entity",
        "external_references",
        ["entity_id", "entity_type"],
    )

    # Step 7: Recreate old check constraints
    op.create_check_constraint(
        "ck_external_references_integration_source",
        "external_references",
        "integration_source IN ('google_contacts', 'immich', 'strava', 'firefly_iii')",
    )
    op.create_check_constraint(
        "ck_external_references_entity_type",
        "external_references",
        "entity_type IN ('contact', 'journal_entry', 'calendar_event', 'photo', 'album', 'activity', 'transaction')",
    )
