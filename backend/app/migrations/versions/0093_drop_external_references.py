"""Drop external_references and the link-backfill quarantine table (ITER15-001 Phase 5)

Revision ID: 0093
Revises: 0092
Create Date: 2026-06-22 00:00:01.000000

Final contract step of consolidating integration entity links onto
``sync_metadata``. By this point every reader and writer has moved to
``sync_metadata`` (Phases 3-4) and the bug-created duplicate contacts plus their
orphaned links have been cleaned up (0092), so the legacy ``external_references``
table — and the temporary ``link_backfill_quarantine`` audit table created by the
0091 backfill — are dropped.

A grep gate over ``backend/app``, ``core_shared`` and ``integration_workers``
confirms no non-migration code references ``external_references`` before this runs.

Downgrade recreates ``external_references`` with the post-0015 schema (no unique
constraint, the three ``ix_external_references_*`` lookup indexes) and the empty
``link_backfill_quarantine`` audit table so the prior revision's shape is
restored. The dropped *data* is not recovered — this is a destructive contract.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0093"
down_revision: str | None = "0092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DDL for the 0091 audit table, reproduced so downgrade restores it.
_CREATE_QUARANTINE = sa.text("""
    CREATE TABLE IF NOT EXISTS link_backfill_quarantine (
        id SERIAL PRIMARY KEY,
        integration_source VARCHAR(50) NOT NULL,
        external_id VARCHAR(255) NOT NULL,
        internal_id INTEGER,
        external_reference_id INTEGER NOT NULL UNIQUE,
        reason VARCHAR(255) NOT NULL,
        quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
""")


def upgrade() -> None:
    """Drop ``external_references`` and the link-backfill quarantine audit table.

    Dropping the tables drops their indexes; ``IF EXISTS`` keeps the migration
    safe if the quarantine table was already cleaned up.
    """
    op.execute(sa.text("DROP TABLE IF EXISTS link_backfill_quarantine"))
    op.drop_table("external_references")


def downgrade() -> None:
    """Recreate the post-0015 ``external_references`` schema and the audit table."""
    op.create_table(
        "external_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("internal_entity_id", sa.Integer(), nullable=False),
        sa.Column("internal_entity_type", sa.VARCHAR(length=50), nullable=False),
        sa.Column("external_system", sa.VARCHAR(length=50), nullable=False),
        sa.Column("external_entity_id", sa.VARCHAR(length=255), nullable=False),
        sa.Column("external_entity_type", sa.String(length=50), nullable=False),
        sa.Column("reference_data", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
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
    op.execute(_CREATE_QUARANTINE)
