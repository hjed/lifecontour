"""give every journal tag an owner: add journal_tags.user_id and assign existing rows

Revision ID: 0127
Revises: 0126
Create Date: 2026-10-09 00:00:00.000000

Journal tags were one global namespace. This revision adds
``journal_tags.user_id`` and gives each existing tag the owner of the journals
that carry it (through ``journal_tag_assignments``). A tag no journal carries
goes to the site's one user, derived by ``app.migrations.owner_derivation`` from
the tables that already record one; that refuses when the data cannot choose,
unless the operator names the owner:
``alembic -x journal_tags_owner=<user_id> upgrade head``.

A tag carried by journals of more than one owner refuses outright, naming it:
whichever owner it took, the other owner's journal would keep a tag that is not
theirs, and the reads keyed by the journal would show it to them. The override
does not resolve that; detach the tag from one owner's journals first.

The column stays nullable and the global name index stays: ``0128`` checks the
data again, assigns anything a writer inserted without an owner, requires the
column, and moves name uniqueness to the owner.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0127"
down_revision: str | None = "0126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0127"

# Every table that records a user at 0126 — a test pins this to the schema.
EVIDENCE_TABLES = (
    "contacts",
    "journals",
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


def refuse_tags_carried_by_several_owners(
    connection: sa.Connection, label: str
) -> None:
    """Raise naming every tag whose journals belong to more than one owner."""
    shared = connection.execute(
        sa.text(
            """
            SELECT t.name, array_agg(DISTINCT j.user_id ORDER BY j.user_id) AS owners
            FROM journal_tags t
            JOIN journal_tag_assignments a ON a.tag_id = t.id
            JOIN journals j ON j.id = a.journal_id
            GROUP BY t.id, t.name
            HAVING count(DISTINCT j.user_id) > 1
            ORDER BY t.name
            """
        )
    ).fetchall()
    if shared:
        described = "; ".join(
            f"{row.name!r} ({', '.join(row.owners)})" for row in shared
        )
        raise RuntimeError(
            f"{label} cannot give these journal tags one owner: journals of "
            f"several users carry them — {described}. Remove each tag from all "
            "but one owner's journals, then re-run."
        )


def upgrade() -> None:
    """Add the owner column, assign existing tags, and index it."""
    op.add_column("journal_tags", sa.Column("user_id", sa.String(50), nullable=True))

    connection = op.get_bind()
    refuse_tags_carried_by_several_owners(connection, _LABEL)

    carried = connection.execute(
        sa.text(
            """
            UPDATE journal_tags t
            SET user_id = owners.user_id
            FROM (
                SELECT DISTINCT a.tag_id, j.user_id
                FROM journal_tag_assignments a
                JOIN journals j ON j.id = a.journal_id
            ) owners
            WHERE owners.tag_id = t.id
            """
        )
    )
    log.info(
        "%s: %d carried tags given their journals' owner.", _LABEL, carried.rowcount
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
        log.info("%s: no uncarried journal tags; nothing more to assign.", _LABEL)

    op.create_index("idx_journal_tags_user_id", "journal_tags", ["user_id"])


def downgrade() -> None:
    """Drop the owner column and its index."""
    op.drop_index("idx_journal_tags_user_id", table_name="journal_tags")
    op.drop_column("journal_tags", "user_id")
