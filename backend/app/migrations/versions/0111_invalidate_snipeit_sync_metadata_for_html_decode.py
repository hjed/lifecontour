"""Invalidate Snipe-IT sync_metadata version hashes for HTML decode

Revision ID: 0111
Revises: 0110
Create Date: 2026-09-14 00:00:00.000000

Sets version_hash to a sentinel for all Snipe-IT gear sync_metadata rows.
Snipe-IT HTML-escapes text in API responses, and gear items were stored with
those entities (e.g. ``-&gt;`` instead of ``->``). The transformer now decodes
asset text once on import; this forces the next Snipe-IT sync to re-process
each asset so existing gear items pick up the decoded name, model,
manufacturer and serial.

version_hash is a SHA-256 of the raw Snipe-IT asset JSON, so a change to the
transformer logic alone does not invalidate existing hashes; this migration
does. After re-processing, the version_hash is repopulated and future syncs
skip unchanged assets as before.

Only the 'snipeit' gear source is touched; 'snipeit_maintenance',
'snipeit_checkout' and 'snipeit_checkin' are separate sources and left as-is.

Operational note: the outbound export path (``push_asset_update`` in
``snipeit_sync_service.py``) uses version_hash for conflict detection and
skips exports while the stored hash does not match the freshly-computed
remote hash. Between this migration and the next inbound sync, a local gear
edit's export is therefore skipped (the local change persists and re-exports
on the next edit). To keep that window small, run an inbound Snipe-IT sync
immediately after deploying this migration -- which is required anyway for the
decode to take effect.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Invalidate version_hash for all Snipe-IT gear sync_metadata entries."""
    op.execute(
        """
        UPDATE sync_metadata
        SET version_hash = 'invalidated_for_html_decode'
        WHERE integration_source = 'snipeit'
        """
    )


def downgrade() -> None:
    """No-op: cannot restore version hashes, they will be repopulated on next sync."""
    pass
