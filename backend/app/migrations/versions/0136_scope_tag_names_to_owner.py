"""make contact tag names unique per owner rather than across all users

Revision ID: 0136
Revises: 0135
Create Date: 2026-10-12 00:00:00.000000

Contact tag names were unique across every user (``uq_tags_name_lower`` on
``LOWER(name)``, from ``0048``). Every read of the tag namespace is now scoped
to its owner, so names are unique per owner instead
(``uq_tags_user_id_name_lower``): two users may each hold a ``family`` tag, and
one user still cannot hold ``Family`` and ``family``. Like ``0129`` for journal
tags, it lands with the owner-scoped reads and never before them.

Going back to one global namespace is impossible while two owners share a
name, so the downgrade refuses then, naming the names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0136"
down_revision: str | None = "0135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Swap the global name index for a per-owner one."""
    op.execute("DROP INDEX uq_tags_name_lower")
    op.create_index(
        "uq_tags_user_id_name_lower",
        "tags",
        ["user_id", sa.text("LOWER(name)")],
        unique=True,
    )


def downgrade() -> None:
    """Restore the global name index, unless owners now share a name."""
    names_held_by_several_owners = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT LOWER(name) FROM tags GROUP BY LOWER(name) "
                "HAVING count(DISTINCT user_id) > 1 ORDER BY 1"
            )
        )
        .scalars()
        .all()
    )
    if names_held_by_several_owners:
        raise RuntimeError(
            "0136 cannot be downgraded: more than one user holds the contact "
            f"tag names {', '.join(map(repr, names_held_by_several_owners))}, "
            "which one global name index cannot allow. Rename or merge them first."
        )
    op.drop_index("uq_tags_user_id_name_lower", table_name="tags")
    op.create_index("uq_tags_name_lower", "tags", [sa.text("LOWER(name)")], unique=True)
