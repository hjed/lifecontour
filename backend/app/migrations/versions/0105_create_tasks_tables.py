"""create tasks, task_intermediate_journals and task_contacts tables

Revision ID: 0105
Revises: 0104
Create Date: 2026-07-31 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0105"
down_revision: str | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the task tables.

    A task is a short plain-text commitment anchored to exactly two journals:
    the ``creating`` journal where it arose and the ``due`` journal where it
    matters. Both anchors are ``NOT NULL`` because a task can never exist with
    only one of them at any point in its life.

    The anchor foreign keys are ``ON DELETE RESTRICT``: deleting a journal that
    anchors a task must be refused rather than silently destroying the task.
    The explanatory, task-naming failure is added in the service layer by
    ITER18-002; until then the database refuses on its own.

    Intermediate journal links and contact links cascade from the task side, and
    also from the journal and contact sides respectively — deleting a journal
    that is only mentioned by a task, or a contact a task references, removes
    the link and leaves the task untouched.
    """
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        # Plain text, deliberately unbounded: anything richer than a short line
        # belongs in a journal, which is a product convention rather than a
        # constraint the column enforces.
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'not_done'"),
            nullable=False,
        ),
        sa.Column("creating_journal_id", sa.Integer(), nullable=False),
        sa.Column("due_journal_id", sa.Integer(), nullable=False),
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
        # Matches the three-value TaskStatus domain enum.
        sa.CheckConstraint(
            "status IN ('not_done', 'done', 'cancelled')",
            name="ck_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["creating_journal_id"],
            ["journals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["due_journal_id"],
            ["journals.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    # The anchor indexes also keep the RESTRICT check on a journal delete cheap.
    op.create_index("ix_tasks_creating_journal_id", "tasks", ["creating_journal_id"])
    op.create_index("ix_tasks_due_journal_id", "tasks", ["due_journal_id"])

    # Journals where the task was discussed, revisited, or previously due. The
    # composite primary key makes link adds idempotent.
    op.create_table(
        "task_intermediate_journals",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "journal_id"),
    )
    op.create_index(
        "ix_task_intermediate_journals_journal_id",
        "task_intermediate_journals",
        ["journal_id"],
    )

    # Plain contact references: no relationship type, role or attendance status.
    op.create_table(
        "task_contacts",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "contact_id"),
    )
    op.create_index(
        "ix_task_contacts_contact_id",
        "task_contacts",
        ["contact_id"],
    )


def downgrade() -> None:
    """Drop the task tables."""
    op.drop_index("ix_task_contacts_contact_id", table_name="task_contacts")
    op.drop_table("task_contacts")
    op.drop_index(
        "ix_task_intermediate_journals_journal_id",
        table_name="task_intermediate_journals",
    )
    op.drop_table("task_intermediate_journals")
    op.drop_index("ix_tasks_due_journal_id", table_name="tasks")
    op.drop_index("ix_tasks_creating_journal_id", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
