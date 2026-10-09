"""give every integration link an owner: add sync_metadata.user_id

Revision ID: 0126
Revises: 0125
Create Date: 2026-10-08 00:00:00.000000

``sync_metadata`` is unique on ``(integration_source, external_id)`` across all
users, so one user's link can block, or be re-pointed by, another's. This
revision is the expand half of moving that key to the owner: it adds a nullable
``sync_metadata.user_id``, gives every existing link the owner of the entity it
points at, and creates the per-user unique index that every writer conflicts on
from this release. The global index stays until ``0128``; while both exist, a
write for an external id another owner already holds is refused by it.

The owner comes from the linked entity, by its type; a link no entity owns is
logged and given the site's one user (``app.migrations.sync_metadata_owner``
describes both, and the ``-x sync_metadata_owner=<user_id>`` override).

The column stays nullable here: ``0128`` assigns anything a not-yet-deployed
writer inserted without an owner, then requires it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.sync_metadata_owner import assign_link_owners

# revision identifiers, used by Alembic.
revision: str = "0126"
down_revision: str | None = "0125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0126"
_PER_USER_INDEX = "uq_sync_metadata_user_source_external"

# Every table that records a user at 0125 — a test pins this to the schema.
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
)


def upgrade() -> None:
    """Add the owner column, assign every link, and index the per-user key."""
    op.add_column("sync_metadata", sa.Column("user_id", sa.String(50), nullable=True))

    assign_link_owners(op.get_bind(), label=_LABEL, evidence_tables=EVIDENCE_TABLES)

    op.create_index(
        _PER_USER_INDEX,
        "sync_metadata",
        ["user_id", "integration_source", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    """Drop the per-user index and the owner column."""
    op.drop_index(_PER_USER_INDEX, table_name="sync_metadata")
    op.drop_column("sync_metadata", "user_id")
