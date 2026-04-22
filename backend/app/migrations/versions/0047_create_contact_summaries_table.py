"""create_contact_summaries_table

Revision ID: 0047
Revises: 0046
Create Date: 2026-04-23 09:11:34.780424

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the contact_summaries table for AI-generated interaction summaries."""
    op.create_table(
        "contact_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "contact_id",
            sa.Integer(),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "follow_up_suggestions",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(30),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "is_disabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_user_override",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("user_override_text", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'generated', 'failed', 'disabled')",
            name="ck_contact_summaries_status",
        ),
    )


def downgrade() -> None:
    """Drop the contact_summaries table."""
    op.drop_table("contact_summaries")
