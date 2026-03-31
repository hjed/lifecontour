"""update tags name check constraint for hierarchical names

Revision ID: 0039
Revises: 0038
Create Date: 2026-03-27

Updates the tags name CHECK constraint to support hierarchical tag names
using '/' as a delimiter. Each segment separated by '/' must be non-empty
and contain only alphanumeric characters, hyphens, underscores, and ampersands.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tags_name_format", "tags", type_="check")
    op.create_check_constraint(
        "ck_tags_name_format",
        "tags",
        "name ~ '^[a-zA-Z0-9_&-]+(/[a-zA-Z0-9_&-]+)*$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tags_name_format", "tags", type_="check")
    op.create_check_constraint(
        "ck_tags_name_format",
        "tags",
        "name ~ '^[a-zA-Z0-9_&-]+$'",
    )
