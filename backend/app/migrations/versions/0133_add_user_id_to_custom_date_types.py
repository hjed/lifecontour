"""give every custom date type an owner: add custom_date_types.user_id and assign existing rows

Revision ID: 0133
Revises: 0132
Create Date: 2026-10-12 00:00:00.000000

Custom date types were one global namespace. This revision adds
``custom_date_types.user_id`` and gives each existing type the owner of the
contacts whose important dates use it (through ``contact_important_dates``).
A type no date uses goes to the site's one user, derived by
``app.migrations.owner_derivation`` from the tables that already record one;
that refuses when the data cannot choose, unless the operator names the owner:
``alembic -x custom_date_types_owner=<user_id> upgrade head``.

A type used by contacts of more than one owner refuses outright, naming it:
whichever owner it took, the other owner's contact would keep a date labelled
by a type that is not theirs. The override does not resolve that; re-type one
owner's dates first.

The column stays nullable and the global name key stays: ``0134`` owns anything
a writer inserted without an owner during the rollout, requires the column, and
moves name uniqueness to the owner together with the owner-scoped reads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0133"
down_revision: str | None = "0132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0133"

# Every table that records a user at 0132 — a test pins this to the schema.
EVIDENCE_TABLES = (
    "contacts",
    "journals",
    "journal_tags",
    "journal_merged_aliases",
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


def refuse_types_used_by_several_owners(connection: sa.Connection, label: str) -> None:
    """Raise naming every type whose dates belong to more than one owner."""
    shared = connection.execute(
        sa.text(
            """
            SELECT t.name, array_agg(DISTINCT c.user_id ORDER BY c.user_id) AS owners
            FROM custom_date_types t
            JOIN contact_important_dates d ON d.custom_date_type_id = t.id
            JOIN contacts c ON c.id = d.contact_id
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
            f"{label} cannot give these custom date types one owner: contacts of "
            f"several users use them — {described}. Re-type the dates of all but "
            "one owner, then re-run."
        )


def own_used_types(connection: sa.Connection, label: str) -> None:
    """Give every unowned type that dates use the owner of those dates' contacts.

    Callers refuse types used by several owners first, so each type has one.
    """
    used = connection.execute(
        sa.text(
            """
            UPDATE custom_date_types t
            SET user_id = owners.user_id
            FROM (
                SELECT DISTINCT d.custom_date_type_id AS type_id, c.user_id
                FROM contact_important_dates d
                JOIN contacts c ON c.id = d.contact_id
                WHERE d.custom_date_type_id IS NOT NULL
            ) owners
            WHERE owners.type_id = t.id AND t.user_id IS NULL
            """
        )
    )
    log.info(
        "%s: %d used custom date types given their contacts' owner.",
        label,
        used.rowcount,
    )


def own_unused_types(
    connection: sa.Connection,
    label: str,
    evidence_tables: Sequence[str],
) -> None:
    """Give every type still without an owner the site's one user."""
    unused = connection.execute(
        sa.text("SELECT count(*) FROM custom_date_types WHERE user_id IS NULL")
    ).scalar_one()
    if not unused:
        log.info("%s: no unused custom date types; nothing more to assign.", label)
        return
    owner = derive_owner(
        connection,
        evidence_tables=evidence_tables,
        label=label,
        override_name="custom_date_types_owner",
    )
    assign_unowned(connection, "custom_date_types", owner, label)


def upgrade() -> None:
    """Add the owner column, assign existing types, and index it."""
    op.add_column(
        "custom_date_types", sa.Column("user_id", sa.String(50), nullable=True)
    )

    connection = op.get_bind()
    refuse_types_used_by_several_owners(connection, _LABEL)
    own_used_types(connection, _LABEL)
    own_unused_types(connection, _LABEL, EVIDENCE_TABLES)

    op.create_index("idx_custom_date_types_user_id", "custom_date_types", ["user_id"])


def downgrade() -> None:
    """Drop the owner column and its index."""
    op.drop_index("idx_custom_date_types_user_id", table_name="custom_date_types")
    op.drop_column("custom_date_types", "user_id")
