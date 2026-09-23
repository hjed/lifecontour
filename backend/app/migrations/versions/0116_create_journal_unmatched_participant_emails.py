"""create journal unmatched participant emails table

Revision ID: 0116
Revises: 0115
Create Date: 2026-09-22 10:00:00.000000

Inbound journal sync resolves each participant email to a contact and, until
now, silently dropped the ones that matched none. This records them per
journal -- lower-cased, with the display name and attendance the integration
reported -- so recurring unknown participants can be suggested as contacts and
linked back to every journal they were on once they are. Nothing here is
integration-specific: any integration that sends participant emails fills it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0116"
down_revision: str | None = "0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "journal_unmatched_participant_emails",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=True),
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
        sa.PrimaryKeyConstraint("journal_id", "email"),
        sa.CheckConstraint(
            "email = lower(email)",
            name="ck_journal_unmatched_participant_emails_lower_email",
        ),
    )
    op.create_index(
        "ix_journal_unmatched_participant_emails_email",
        "journal_unmatched_participant_emails",
        ["email"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index(
        "ix_journal_unmatched_participant_emails_email",
        table_name="journal_unmatched_participant_emails",
    )
    op.drop_table("journal_unmatched_participant_emails")
