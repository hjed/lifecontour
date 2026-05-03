"""create gear items table

Revision ID: 0063
Revises: c385507821a1
Create Date: 2026-05-03 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0063"
down_revision: str | None = "c385507821a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gear_items",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("serial_number", sa.String(200), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("manufacturer", sa.String(200), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gear_items_user_id", "gear_items", ["user_id"])
    op.create_index("ix_gear_items_user_name", "gear_items", ["user_id", "name"])


def downgrade() -> None:
    op.drop_index("ix_gear_items_user_name", table_name="gear_items")
    op.drop_index("ix_gear_items_user_id", table_name="gear_items")
    op.drop_table("gear_items")
