"""Decode HTML-escaped Snipe-IT gear text in place

Revision ID: 0111
Revises: 0110
Create Date: 2026-09-15 00:00:00.000000

Snipe-IT HTML-escapes text in API responses (``'`` as ``&#039;``, ``&`` as
``&amp;``) but stores what it is sent, and gear items were imported with those
entities. The Snipe-IT transformer now decodes asset text once on import; this
migration decodes the gear text that is already stored.

The stored text is decoded in place rather than by invalidating
``sync_metadata.version_hash`` (as 0096 did) to force a re-import. With an
invalidated hash, ``push_asset_update`` skips exporting a local gear edit as a
conflict, and the next inbound sync then overwrites that edit with the remote
values, so edits made before that sync would be lost. Leaving the hash alone
avoids that window and needs no post-deploy sync.

Only ``name``, ``model``, ``manufacturer`` and ``serial_number`` of gear items
linked to a ``snipeit`` sync row are considered, and a value is decoded only
when it is exactly Snipe-IT's escaped output: re-escaping the decoded text the
way Laravel's ``e()`` does must give back the stored value. That leaves alone:

- raw text from a local edit, which ``push_asset_update`` stores as typed
  (a bare ``&`` or ``'`` does not survive the round trip);
- a value truncated mid-entity (``...&am``);
- plain text with nothing to decode.

A local edit that is itself valid escaped output (a user literally typing
``&amp;``) would be decoded; that is accepted as vanishingly rare.
"""

import html

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0111"
down_revision: str | None = "0110"
branch_labels: str | None = None
depends_on: str | None = None

_TEXT_COLUMNS = ("name", "model", "manufacturer", "serial_number")

# Laravel's e() (htmlspecialchars with ENT_QUOTES), which Snipe-IT applies to
# API output. "&" must be replaced first so the other entities are not escaped.
_LARAVEL_ENTITIES = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("'", "&#039;"),
)


def _laravel_escape(value: str) -> str:
    """Escape ``value`` the way Snipe-IT escapes text in API responses."""
    for char, entity in _LARAVEL_ENTITIES:
        value = value.replace(char, entity)
    return value


def _decoded_if_escaped(value: str | None) -> str | None:
    """Return the decoded value if ``value`` is Snipe-IT escaped output, else None."""
    if value is None:
        return None
    decoded = html.unescape(value)
    if decoded == value or _laravel_escape(decoded) != value:
        return None
    return decoded


def upgrade() -> None:
    """Decode Snipe-IT-escaped text on gear items synced from Snipe-IT."""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT g.id, g.name, g.model, g.manufacturer, g.serial_number
            FROM gear_items g
            JOIN sync_metadata s ON s.internal_uuid = g.id::text
            WHERE s.integration_source = 'snipeit'
            """
        )
    ).mappings()

    for row in rows.all():
        decoded = {
            column: value
            for column in _TEXT_COLUMNS
            if (value := _decoded_if_escaped(row[column])) is not None
        }
        if not decoded:
            continue
        assignments = ", ".join(f"{column} = :{column}" for column in decoded)
        connection.execute(
            sa.text(f"UPDATE gear_items SET {assignments} WHERE id = :id"),
            {**decoded, "id": row["id"]},
        )


def downgrade() -> None:
    """No-op: the original escaping is not worth restoring."""
    pass
