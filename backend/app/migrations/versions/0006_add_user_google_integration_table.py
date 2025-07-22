"""Add user_google_integration table

Revision ID: 0006
Revises: 0005
Create Date: 2025-01-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user_google_integration table for storing sync tokens."""
    op.create_table(
        'user_google_integration',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False, comment='Site user identifier'),
        sa.Column('google_account_email', sa.String(length=255), nullable=False, comment='Google account email address'),
        sa.Column('contacts_sync_token', sa.String(length=500), nullable=True, comment='Google Contacts sync token for incremental sync'),
        sa.Column('last_contacts_sync_at', sa.DateTime(timezone=True), nullable=True, comment='Last successful contacts sync timestamp'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='Record creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='Record last update timestamp'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'google_account_email', name='uq_user_google_integration')
    )
    op.create_index(op.f('ix_user_google_integration_google_account_email'), 'user_google_integration', ['google_account_email'], unique=False)
    op.create_index(op.f('ix_user_google_integration_user_id'), 'user_google_integration', ['user_id'], unique=False)


def downgrade() -> None:
    """Remove user_google_integration table."""
    op.drop_index(op.f('ix_user_google_integration_user_id'), table_name='user_google_integration')
    op.drop_index(op.f('ix_user_google_integration_google_account_email'), table_name='user_google_integration')
    op.drop_table('user_google_integration')
