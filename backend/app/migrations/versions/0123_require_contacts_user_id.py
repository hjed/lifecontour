"""every contact has an owner: make contacts.user_id NOT NULL

Revision ID: 0123
Revises: 0122
Create Date: 2026-10-01 00:00:00.000000

``0122`` added ``contacts.user_id`` and assigned every contact that existed then.
Until the release that made every writer stamp an owner, a contact created
through REST or MCP still inserted ``NULL``. This revision assigns those rows by
the same derivation — with owned contacts now counted as evidence, so a
contacts-only installation resolves to the owner ``0122`` already chose — and
then makes an unowned contact impossible.

Rows still unowned with no owner evidence refuse, as in ``0122``, unless the
operator names the owner: ``alembic -x contacts_owner=<user_id> upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import assign_unowned, derive_owner, log

# revision identifiers, used by Alembic.
revision: str = "0123"
down_revision: str | None = "0122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0123"

# 0122's evidence, plus the owned contacts themselves.
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
)


def upgrade() -> None:
    """Assign any contact still unowned, then require an owner."""
    connection = op.get_bind()
    unowned = connection.execute(
        sa.text("SELECT count(*) FROM contacts WHERE user_id IS NULL")
    ).scalar_one()
    if unowned:
        owner = derive_owner(
            connection,
            evidence_tables=EVIDENCE_TABLES,
            label=_LABEL,
            override_name="contacts_owner",
        )
        assign_unowned(connection, "contacts", owner, _LABEL)
    else:
        log.info("%s: every contact already has an owner.", _LABEL)

    op.alter_column("contacts", "user_id", existing_type=sa.String(50), nullable=False)


def downgrade() -> None:
    """Allow an unowned contact again."""
    op.alter_column("contacts", "user_id", existing_type=sa.String(50), nullable=True)
