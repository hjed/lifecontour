"""create_user_immich_auth

Revision ID: 0079
Revises: 0078
Create Date: 2026-05-25 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_immich_auth",
        sa.Column(
            "user_id",
            sa.String(length=50),
            primary_key=True,
            comment="Site user identifier",
        ),
        sa.Column(
            "server_url",
            sa.String(length=500),
            nullable=False,
            comment="Immich instance base URL",
        ),
        sa.Column(
            "encrypted_api_key",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet-encrypted Immich API key",
        ),
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
        comment="Stores encrypted Immich API keys and server URLs for users",
    )


def downgrade() -> None:
    op.drop_table("user_immich_auth")
