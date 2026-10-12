"""require custom_date_types.user_id and make type names unique per owner

Revision ID: 0134
Revises: 0133
Create Date: 2026-10-12 00:00:00.000000

``0133`` gave every custom date type an owner but left the column nullable and
names unique across all users (``custom_date_types_name_key``). Every writer
now stamps an owner and every read of the namespace is scoped to it, so this
revision:

1. owns any type still without one, as ``0133`` did — a pod still running the
   pre-``0133`` code during the rollout inserts types without an owner; a used
   type takes its contacts' owner, an unused one the site's one user
   (``alembic -x custom_date_types_owner=<user_id>`` when the data cannot
   choose);
2. refuses if any contact's important date uses another owner's type: until
   reads were scoped, every user listed and picked from one namespace, so that
   has to be untangled by hand;
3. makes the column ``NOT NULL``;
4. replaces ``custom_date_types_name_key (name)`` with
   ``uq_custom_date_types_user_id_name (user_id, name)``, so two users may each
   hold a ``Sobriety`` type while one user still cannot hold it twice. Names
   stay case-sensitive, as the global key was.

The downgrade restores the global key and the nullable column, so it refuses
while two owners hold the same name.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0134"
down_revision: str | None = "0133"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0134"
_TABLE = "custom_date_types"
_GLOBAL_KEY = "custom_date_types_name_key"
_PER_USER_KEY = "uq_custom_date_types_user_id_name"

# Every table that records a user at 0133 — a test pins this to the schema.
EVIDENCE_TABLES = (
    "contacts",
    "custom_date_types",
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


def _own_stragglers(connection: sa.Connection) -> None:
    """Give every type still without an owner one, as 0133 did.

    A straggler used by several owners takes one of them here and is then
    refused by ``_refuse_foreign_dates``.
    """
    used = connection.execute(
        sa.text(
            """
            UPDATE custom_date_types t
            SET user_id = owners.user_id
            FROM (
                SELECT d.custom_date_type_id AS type_id, min(c.user_id) AS user_id
                FROM contact_important_dates d
                JOIN contacts c ON c.id = d.contact_id
                WHERE d.custom_date_type_id IS NOT NULL
                GROUP BY d.custom_date_type_id
            ) owners
            WHERE owners.type_id = t.id AND t.user_id IS NULL
            """
        )
    )
    log.info(
        "%s: %d unowned used types given their contacts' owner.",
        _LABEL,
        used.rowcount,
    )

    unused = connection.execute(
        sa.text("SELECT count(*) FROM custom_date_types WHERE user_id IS NULL")
    ).scalar_one()
    if not unused:
        log.info("%s: no unowned custom date types left.", _LABEL)
        return
    owner = derive_owner(
        connection,
        evidence_tables=EVIDENCE_TABLES,
        label=_LABEL,
        override_name="custom_date_types_owner",
    )
    assign_unowned(connection, _TABLE, owner, _LABEL)


def _refuse_foreign_dates(connection: sa.Connection) -> None:
    """Raise naming every type a contact of a different owner's date uses."""
    foreign = connection.execute(
        sa.text(
            """
            SELECT t.name, t.user_id AS owner,
                   array_agg(DISTINCT c.user_id ORDER BY c.user_id) AS users
            FROM custom_date_types t
            JOIN contact_important_dates d ON d.custom_date_type_id = t.id
            JOIN contacts c ON c.id = d.contact_id
            WHERE c.user_id <> t.user_id
            GROUP BY t.id, t.name, t.user_id
            ORDER BY t.name
            """
        )
    ).fetchall()
    if foreign:
        described = "; ".join(
            f"{row.name!r} (owned by {row.owner}, used by contacts of "
            f"{', '.join(row.users)})"
            for row in foreign
        )
        raise RuntimeError(
            f"{_LABEL} cannot require custom date type owners: contacts' dates use "
            f"types another user owns — {described}. Re-type those dates with a "
            "type of their contact's owner, then re-run."
        )


def upgrade() -> None:
    """Own the stragglers, refuse cross-owner dates, require the owner, scope names."""
    connection = op.get_bind()
    _own_stragglers(connection)
    _refuse_foreign_dates(connection)

    op.alter_column(_TABLE, "user_id", nullable=False)
    op.drop_constraint(_GLOBAL_KEY, _TABLE, type_="unique")
    op.create_unique_constraint(_PER_USER_KEY, _TABLE, ["user_id", "name"])


def downgrade() -> None:
    """Restore the global name key and the optional owner.

    Refuses while two owners share a name, which the global key would reject.
    """
    connection = op.get_bind()
    shared = connection.execute(
        sa.text(
            """
            SELECT name FROM custom_date_types
            GROUP BY name
            HAVING count(*) > 1
            ORDER BY name
            """
        )
    ).fetchall()
    if shared:
        raise RuntimeError(
            f"{_LABEL} cannot be downgraded: several users hold the custom date "
            f"type names {', '.join(repr(row.name) for row in shared)}, which the "
            "global name key would reject. Rename or delete them first."
        )

    op.drop_constraint(_PER_USER_KEY, _TABLE, type_="unique")
    op.create_unique_constraint(_GLOBAL_KEY, _TABLE, ["name"])
    op.alter_column(_TABLE, "user_id", nullable=True)
