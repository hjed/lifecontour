"""make journal tag names unique per owner rather than across all users

Revision ID: 0129
Revises: 0128
Create Date: 2026-10-09 00:00:00.000000

Journal tag names were unique across every user (``uq_journal_tags_name_lower``
on ``LOWER(name)``). Every read of the tag namespace is now scoped to its owner,
so this revision replaces that index with
``uq_journal_tags_user_id_name_lower (user_id, LOWER(name))``: two users may each
hold a ``family`` tag, while one user still cannot hold ``Family`` and ``family``.

It lands with the owner-scoped reads, never before them: while a name lookup was
global, a second user's ``Family`` would have let a journal's tag-name list pick
up the first user's tag.

The downgrade restores the global index, so it refuses while two owners hold the
same name.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0129"
down_revision: str | None = "0128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0129"
_GLOBAL_INDEX = "uq_journal_tags_name_lower"
_PER_USER_INDEX = "uq_journal_tags_user_id_name_lower"


def upgrade() -> None:
    """Scope name uniqueness to the owner."""
    op.drop_index(_GLOBAL_INDEX, table_name="journal_tags")
    op.execute(
        f"CREATE UNIQUE INDEX {_PER_USER_INDEX} ON journal_tags (user_id, LOWER(name))"
    )


def downgrade() -> None:
    """Restore the global name index, refusing while two owners share a name."""
    connection = op.get_bind()
    shared = connection.execute(
        sa.text(
            """
            SELECT LOWER(name) AS name
            FROM journal_tags
            GROUP BY LOWER(name)
            HAVING count(*) > 1
            ORDER BY 1
            """
        )
    ).fetchall()
    if shared:
        raise RuntimeError(
            f"{_LABEL} cannot be downgraded: several users hold the journal tag "
            f"names {', '.join(repr(row.name) for row in shared)}, which the "
            "global name index would reject. Rename or merge them first."
        )

    op.drop_index(_PER_USER_INDEX, table_name="journal_tags")
    op.execute(f"CREATE UNIQUE INDEX {_GLOBAL_INDEX} ON journal_tags (LOWER(name))")
