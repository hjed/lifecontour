"""restore the Immich avatar of every contact linked to an Immich person

Revision ID: 0144
Revises: 0143
Create Date: 2026-11-11 00:00:00.000000

Until inbound contact syncs were limited to the fields their source owns
(``core_shared.models.contacts.sync_scope``), every Google update saved the
whole contact and wrote ``photo_url = NULL`` over the Immich avatar. And until
the name-match auto-link forced its event through, a contact Immich linked by
name never received the avatar at all. Both are fixed, but neither repairs
itself: the Immich pull skips a linked person whose version has not moved, so
a contact whose person is unchanged in Immich never gets its avatar back.

The avatar URL is derived - the proxy endpoint for the contact's own id, as
the Immich worker writes it - so it is set directly for every contact without
one whose owner links it to an Immich person. ``updated_at`` is left alone: a
repaired contact holds no local edit, and bumping it would queue a push of
every one of them to Google and Immich.

The downgrade is a no-op: the restored value is correct, and a repaired row
cannot be told apart from one the sync set.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give each owner-linked Immich contact without a photo its avatar URL."""
    op.execute("""
        UPDATE contacts c
        SET photo_url = '/api/contacts/' || c.id || '/avatar'
        WHERE c.photo_url IS NULL
          AND EXISTS (
              SELECT 1
              FROM sync_metadata sm
              WHERE sm.integration_source = 'immich'
                AND sm.internal_entity_type = 'contact'
                AND sm.external_entity_type = 'person'
                AND sm.internal_id IS NOT NULL
                AND sm.internal_id = c.id
                AND sm.user_id = c.user_id
          )
    """)


def downgrade() -> None:
    """Nothing to undo: the restored avatar URL is the correct value."""
