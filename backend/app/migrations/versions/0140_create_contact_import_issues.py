"""create contact_import_issues

Revision ID: 0140
Revises: 0139
Create Date: 2026-10-23 00:00:00.000000

What an integration import left out of a contact for the user to review
(#1820): today, a Google address whose AU/US/CA region names no state,
province or territory. Each applied import replaces the contact's rows from
that source, so fixing the address at the source clears it; a dismissed row
stays dismissed for as long as the same payload keeps arriving.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0140"
down_revision: str | None = "0139"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_import_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("integration_source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "kind IN ('skipped_address')", name="ck_contact_import_issues_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dismissed')", name="ck_contact_import_issues_status"
        ),
        sa.UniqueConstraint(
            "user_id",
            "contact_id",
            "integration_source",
            "kind",
            "payload_hash",
            name="uq_contact_import_issues_payload",
        ),
    )
    op.create_index(
        "ix_contact_import_issues_user_status",
        "contact_import_issues",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_contact_import_issues_user_status", "contact_import_issues")
    op.drop_table("contact_import_issues")
