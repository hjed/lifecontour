"""give every contact an owner: add contacts.user_id and assign existing rows

Revision ID: 0122
Revises: 0121
Create Date: 2026-10-01 00:00:00.000000

Contacts were the one user-created entity without an owner. This revision adds
``contacts.user_id`` and hands every existing contact to the site's one user,
derived by ``app.migrations.owner_derivation`` from the tables that already
record one. Beyond the content tables ``0106`` repaired, the evidence includes
the credential and settings tables: they are only ever written by the signed-in
user, and they are what identifies the owner of an installation that has only
ever synced contacts (through Google, say) and holds no journal, task or calendar.

A database without contacts has nothing to assign. One with contacts but no
owner evidence, or with more than one real owner, refuses unless the operator
names the owner: ``alembic -x contacts_owner=<user_id> upgrade head``.

The column stays nullable here. Until every writer stamps an owner, a contact
created through REST or MCP still inserts ``NULL``; ``0123`` assigns those rows
by the same derivation and then makes the column ``NOT NULL``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0122"
down_revision: str | None = "0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0122"

# Every table that records a user at this revision. Kept literal so the
# revision keeps meaning the same thing however the schema moves on.
EVIDENCE_TABLES = (
    # Content tables (0106's REPAIRED_TABLES).
    "journals",
    "calendars",
    "gear_items",
    "journal_series",
    "activity_templates",
    "tasks",
    "outdoor_activity_dismissals",
    "journal_review_items",
    "strava_athlete_mappings",
    # Credential, settings and integration-state tables.
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
)


def upgrade() -> None:
    """Add the owner column, assign existing contacts, and index it."""
    op.add_column("contacts", sa.Column("user_id", sa.String(50), nullable=True))

    connection = op.get_bind()
    contacts = connection.execute(sa.text("SELECT count(*) FROM contacts")).scalar_one()
    if contacts:
        owner = derive_owner(
            connection,
            evidence_tables=EVIDENCE_TABLES,
            label=_LABEL,
            override_name="contacts_owner",
        )
        assign_unowned(connection, "contacts", owner, _LABEL)
    else:
        log.info("%s: no contacts; nothing to assign.", _LABEL)

    op.create_index("idx_contacts_user_id", "contacts", ["user_id"])


def downgrade() -> None:
    """Drop the owner column and its index."""
    op.drop_index("idx_contacts_user_id", table_name="contacts")
    op.drop_column("contacts", "user_id")
