"""Add to_user flag to contact_relationships

Revision ID: 0046
Revises: 0045
Create Date: 2026-04-20 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # 1. Add to_user column with default false
    op.add_column(
        "contact_relationships",
        sa.Column(
            "to_user",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # 2. Make to_contact_id nullable (required for user-targeted relationships)
    op.alter_column(
        "contact_relationships",
        "to_contact_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 3. Drop old constraints that assumed to_contact_id is always set
    op.drop_constraint(
        "uq_contact_relationships_unique_relationship",
        "contact_relationships",
        type_="unique",
    )
    op.drop_constraint(
        "ck_contact_relationships_no_self_reference",
        "contact_relationships",
        type_="check",
    )

    # 4. Add check: to_user/to_contact_id consistency
    #    (to_user=true AND to_contact_id IS NULL) OR (to_user=false AND to_contact_id IS NOT NULL)
    op.create_check_constraint(
        "ck_contact_relationships_target_consistency",
        "contact_relationships",
        "(to_user = true AND to_contact_id IS NULL) OR (to_user = false AND to_contact_id IS NOT NULL)",
    )

    # 5. Self-reference check only for contact-to-contact relationships
    op.create_check_constraint(
        "ck_contact_relationships_no_self_reference",
        "contact_relationships",
        "to_user = true OR from_contact_id != to_contact_id",
    )

    # 6. Partial unique index for contact-to-contact relationships
    op.create_index(
        "uq_contact_relationships_contact_target",
        "contact_relationships",
        ["from_contact_id", "to_contact_id", "relationship_type"],
        unique=True,
        postgresql_where=sa.text("to_user = false"),
    )

    # 7. Partial unique index for user-targeted relationships
    op.create_index(
        "uq_contact_relationships_user_target",
        "contact_relationships",
        ["from_contact_id", "relationship_type"],
        unique=True,
        postgresql_where=sa.text("to_user = true"),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop new indexes
    op.drop_index(
        "uq_contact_relationships_user_target",
        table_name="contact_relationships",
    )
    op.drop_index(
        "uq_contact_relationships_contact_target",
        table_name="contact_relationships",
    )

    # Drop new constraints
    op.drop_constraint(
        "ck_contact_relationships_no_self_reference",
        "contact_relationships",
        type_="check",
    )
    op.drop_constraint(
        "ck_contact_relationships_target_consistency",
        "contact_relationships",
        type_="check",
    )

    # Delete any user-targeted rows (to_contact_id IS NULL) before restoring NOT NULL
    op.execute("DELETE FROM contact_relationships WHERE to_user = true")

    # Restore original constraints
    op.create_unique_constraint(
        "uq_contact_relationships_unique_relationship",
        "contact_relationships",
        ["from_contact_id", "to_contact_id", "relationship_type"],
    )
    op.create_check_constraint(
        "ck_contact_relationships_no_self_reference",
        "contact_relationships",
        "from_contact_id != to_contact_id",
    )

    # Make to_contact_id NOT NULL again
    op.alter_column(
        "contact_relationships",
        "to_contact_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Drop to_user column
    op.drop_column("contact_relationships", "to_user")
