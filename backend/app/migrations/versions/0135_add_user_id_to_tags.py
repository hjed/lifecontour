"""give every contact tag an owner: add tags.user_id, assign existing rows, require it

Revision ID: 0135
Revises: 0134
Create Date: 2026-10-12 00:00:00.000000

Contact tags were one global namespace. This revision adds ``tags.user_id`` and
gives each existing tag the owner of the contacts that carry it (through
``contact_tags``). A tag no contact carries goes to the site's one user, derived
by ``app.migrations.owner_derivation`` from the tables that already record one;
that refuses when the data cannot choose, unless the operator names the owner:
``alembic -x tags_owner=<user_id> upgrade head``.

Two shapes refuse outright, naming the tags, and the override resolves neither:

- a tag carried by contacts of more than one owner — whichever owner it took,
  the other owner's contact would keep a tag that is not theirs;
- a tag under another owner's tag — each owner would see part of the other's
  tree.

Contacts already have a required owner, so every tag is assignable here and the
column is required in the same revision (journal tags needed two, ``0127`` and
``0128``, only to keep each PR small). Name uniqueness stays global: it moves to
the owner with the owner-scoped reads, in a later revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0135"
down_revision: str | None = "0134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0135"

# Every table that records a user at 0134 — a test pins this to the schema.
EVIDENCE_TABLES = tuple(
    """
    contacts journals journal_tags calendars gear_items journal_series
    activity_templates tasks outdoor_activity_dismissals journal_review_items
    strava_athlete_mappings user_google_auth user_google_integration
    user_immich_auth user_strava_auth user_snipe_it_auth snipeit_settings
    user_settings sync_jobs calendar_sync_tokens pending_entity_mappings
    contact_suggestion_ignores journal_daily_summaries field_history
    journal_series_recurrence_aliases sync_metadata journal_merged_aliases
    custom_date_types
    """.split()
)


def _refuse_tags_carried_by_several_owners(connection: sa.Connection) -> None:
    """Raise naming every tag whose contacts belong to more than one owner."""
    shared = connection.execute(
        sa.text(
            """
            SELECT t.name, array_agg(DISTINCT c.user_id ORDER BY c.user_id) AS owners
            FROM tags t
            JOIN contact_tags ct ON ct.tag_id = t.id
            JOIN contacts c ON c.id = ct.contact_id
            GROUP BY t.id, t.name
            HAVING count(DISTINCT c.user_id) > 1
            ORDER BY t.name
            """
        )
    ).fetchall()
    if shared:
        described = "; ".join(
            f"{row.name!r} ({', '.join(row.owners)})" for row in shared
        )
        raise RuntimeError(
            f"{_LABEL} cannot give these contact tags one owner: contacts of "
            f"several users carry them — {described}. Remove each tag from all "
            "but one owner's contacts, then re-run."
        )


def _refuse_cross_owner_hierarchy(connection: sa.Connection) -> None:
    """Raise naming every tag whose parent belongs to a different owner."""
    crossing = connection.execute(
        sa.text(
            """
            SELECT child.name AS child, child.user_id AS child_owner,
                   parent.name AS parent, parent.user_id AS parent_owner
            FROM tags child
            JOIN tags parent ON parent.id = child.parent_id
            WHERE parent.user_id <> child.user_id
            ORDER BY child.name
            """
        )
    ).fetchall()
    if crossing:
        described = "; ".join(
            f"{row.child!r} (owned by {row.child_owner}) under {row.parent!r} "
            f"(owned by {row.parent_owner})"
            for row in crossing
        )
        raise RuntimeError(
            f"{_LABEL} cannot give contact tags owners: these tags sit under "
            f"another owner's tag — {described}. Move each to the root or under "
            "a tag of its own owner, then re-run."
        )


def upgrade() -> None:
    """Add the owner column, assign existing tags, check them, and require it."""
    op.add_column("tags", sa.Column("user_id", sa.String(50), nullable=True))

    connection = op.get_bind()
    _refuse_tags_carried_by_several_owners(connection)

    carried = connection.execute(
        sa.text(
            """
            UPDATE tags t
            SET user_id = owners.user_id
            FROM (
                SELECT DISTINCT ct.tag_id, c.user_id
                FROM contact_tags ct
                JOIN contacts c ON c.id = ct.contact_id
            ) owners
            WHERE owners.tag_id = t.id
            """
        )
    )
    log.info(
        "%s: %d carried tags given their contacts' owner.", _LABEL, carried.rowcount
    )

    uncarried = connection.execute(
        sa.text("SELECT count(*) FROM tags WHERE user_id IS NULL")
    ).scalar_one()
    if uncarried:
        owner = derive_owner(
            connection,
            evidence_tables=EVIDENCE_TABLES,
            label=_LABEL,
            override_name="tags_owner",
        )
        assign_unowned(connection, "tags", owner, _LABEL)
    else:
        log.info("%s: no uncarried contact tags; nothing more to assign.", _LABEL)

    _refuse_cross_owner_hierarchy(connection)

    op.alter_column("tags", "user_id", nullable=False)
    op.create_index("idx_tags_user_id", "tags", ["user_id"])


def downgrade() -> None:
    """Drop the owner column and its index."""
    op.drop_index("idx_tags_user_id", table_name="tags")
    op.drop_column("tags", "user_id")
