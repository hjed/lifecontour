"""require journal_tags.user_id

Revision ID: 0128
Revises: 0127
Create Date: 2026-10-09 00:00:00.000000

``0127`` gave every journal tag an owner but left the column nullable and the
case-insensitive name index global (``uq_journal_tags_name_lower``). Every
writer now stamps an owner, so this revision:

1. owns any tag still without one, as ``0127`` did — a carried tag takes its
   journals' owner, an uncarried one the site's one user
   (``alembic -x journal_tags_owner=<user_id>`` when the data cannot choose);
2. refuses if any journal carries a tag of another owner. Until reads were
   scoped, a tag name was looked up across all users, so a second user naming an
   existing tag was given the first user's; that has to be untangled by hand;
3. refuses if a tag's parent belongs to another owner: ``0127`` gives a carried
   tag its journals' owner and an uncarried one the site's, so a parent and
   child can land with different owners, and a hierarchy never links two;
4. makes the column ``NOT NULL``.

Name uniqueness stays global here: ``0129`` scopes it to the owner together
with the owner-scoped reads, since a name lookup that is still global must not
find two tags of one name.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0128"
down_revision: str | None = "0127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0128"

# Every table that records a user at 0127 — a test pins this to the schema.
EVIDENCE_TABLES = (
    "contacts",
    "journals",
    "journal_tags",
    "calendars",
    "gear_items",
    "journal_series",
    "activity_templates",
    "tasks",
    "outdoor_activity_dismissals",
    "journal_review_items",
    "strava_athlete_mappings",
    "user_google_auth",
    "user_google_integration",
    "user_immich_auth",
    "user_strava_auth",
    "user_snipe_it_auth",
    "snipeit_settings",
    "user_settings",
    "sync_jobs",
    "calendar_sync_tokens",
    "pending_entity_mappings",
    "contact_suggestion_ignores",
    "journal_daily_summaries",
    "field_history",
    "journal_series_recurrence_aliases",
    "sync_metadata",
)


def _own_stragglers(connection: sa.Connection) -> None:
    """Give every tag still without an owner one, exactly as 0127 did."""
    carried = connection.execute(
        sa.text(
            """
            UPDATE journal_tags t
            SET user_id = owners.user_id
            FROM (
                SELECT a.tag_id, min(j.user_id) AS user_id
                FROM journal_tag_assignments a
                JOIN journals j ON j.id = a.journal_id
                GROUP BY a.tag_id
            ) owners
            WHERE owners.tag_id = t.id AND t.user_id IS NULL
            """
        )
    )
    log.info(
        "%s: %d unowned carried tags given their journals' owner.",
        _LABEL,
        carried.rowcount,
    )

    uncarried = connection.execute(
        sa.text("SELECT count(*) FROM journal_tags WHERE user_id IS NULL")
    ).scalar_one()
    if uncarried:
        owner = derive_owner(
            connection,
            evidence_tables=EVIDENCE_TABLES,
            label=_LABEL,
            override_name="journal_tags_owner",
        )
        assign_unowned(connection, "journal_tags", owner, _LABEL)
    else:
        log.info("%s: no unowned journal tags left.", _LABEL)


def _refuse_foreign_assignments(connection: sa.Connection) -> None:
    """Raise naming every tag a journal of a different owner carries.

    A straggler carried by several owners is caught here too: ``_own_stragglers``
    gave it one of them, so the other's journal now carries a foreign tag.
    """
    foreign = connection.execute(
        sa.text(
            """
            SELECT t.name, t.user_id AS owner,
                   array_agg(DISTINCT j.user_id ORDER BY j.user_id) AS carriers
            FROM journal_tags t
            JOIN journal_tag_assignments a ON a.tag_id = t.id
            JOIN journals j ON j.id = a.journal_id
            WHERE j.user_id <> t.user_id
            GROUP BY t.id, t.name, t.user_id
            ORDER BY t.name
            """
        )
    ).fetchall()
    if foreign:
        described = "; ".join(
            f"{row.name!r} (owned by {row.owner}, carried by journals of "
            f"{', '.join(row.carriers)})"
            for row in foreign
        )
        raise RuntimeError(
            f"{_LABEL} cannot require journal tag owners: journals carry tags "
            f"another user owns — {described}. Remove those assignments, or give "
            "that user a tag of their own, then re-run."
        )


def _refuse_cross_owner_hierarchy(connection: sa.Connection) -> None:
    """Raise naming every tag whose parent belongs to a different owner."""
    crossing = connection.execute(
        sa.text(
            """
            SELECT child.name AS child, child.user_id AS child_owner,
                   parent.name AS parent, parent.user_id AS parent_owner
            FROM journal_tags child
            JOIN journal_tags parent ON parent.id = child.parent_id
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
            f"{_LABEL} cannot require journal tag owners: these tags sit under "
            f"another owner's tag — {described}. Move each to the root or under "
            "a tag of its own owner, then re-run."
        )


def upgrade() -> None:
    """Own the stragglers, refuse cross-owner links, and require the owner."""
    connection = op.get_bind()
    _own_stragglers(connection)
    _refuse_foreign_assignments(connection)
    _refuse_cross_owner_hierarchy(connection)

    op.alter_column("journal_tags", "user_id", nullable=False)


def downgrade() -> None:
    """Make the owner optional again."""
    op.alter_column("journal_tags", "user_id", nullable=True)
