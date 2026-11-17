"""create the task_lists table

Revision ID: 0145
Revises: 0144
Create Date: 2026-11-17 00:00:00.000000

A task list is a user's named home for tasks: a name, an optional icon from the
fixed ``TaskIcon`` set, a position among the owner's lists and an archived
state. Tasks join lists in a later migration; the list kind, journal
association and template columns arrive with the phases that use them.

The CHECKs repeat the ``TaskList`` entity's name and position rules as a last
line of defence (as with ``tasks``, a blank owner is refused by the entity only).
There is deliberately **no** CHECK on ``icon``: the set is add-only and shared
with ``tasks.icon``, so a CHECK would cost a migration on two tables for every
new icon, and every write already goes through the entity, which accepts only a
``TaskIcon``.

Positions are not unique: reordering shifts many rows at once, and lists order
by ``(position, id)``, so the order is total even if two lists share a position.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0145"
down_revision: str | None = "0144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``task_lists`` and its owner-ordered index."""
    op.create_table(
        "task_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name="ck_task_lists_name_not_blank",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_task_lists_position_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Every read is owner-scoped and ordered by position, so one composite
    # index serves both the scoping and the order.
    op.create_index(
        "ix_task_lists_user_id_position", "task_lists", ["user_id", "position"]
    )


def downgrade() -> None:
    """Drop ``task_lists``."""
    op.drop_index("ix_task_lists_user_id_position", table_name="task_lists")
    op.drop_table("task_lists")
