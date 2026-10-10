"""every integration link has an owner, and is keyed by it alone

Revision ID: 0130
Revises: 0129
Create Date: 2026-10-09 00:00:00.000000

``0126`` gave every link an owner and created the per-user unique index
``(user_id, integration_source, external_id)`` that every writer conflicts on,
but left the column nullable for a writer not yet deployed. This revision is
the contract half:

- every link still unowned takes its entity's owner, or — when no entity owns
  it — the site's one owner, logged (``app.migrations.sync_metadata_owner``);
  this refuses when the data cannot choose, unless the operator names the
  owner: ``alembic -x sync_metadata_owner=<user_id> upgrade head``;
- ``sync_metadata.user_id`` becomes NOT NULL;
- the global ``(integration_source, external_id)`` index is dropped, so two
  users may each link the same external id — two Snipe-IT instances hand out
  the same asset ids. Every lookup, update and delete is keyed by the owner.

Downgrading restores the global index and the nullable column, refusing while
two owners hold the same external id: the old key cannot represent that.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.migrations.owner_derivation import log
from app.migrations.sync_metadata_owner import assign_link_owners

# revision identifiers, used by Alembic.
revision: str = "0130"
down_revision: str | None = "0129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LABEL = "0130"
_GLOBAL_INDEX = "idx_sync_metadata_integration_external"

# 0126's evidence, plus the owned links and the journal tags 0127 gave an owner
# — every table holding a user_id at 0129, as a test pins.
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
    "journal_tags",
)


def upgrade() -> None:
    """Assign any link still unowned, require an owner, drop the global key."""
    connection = op.get_bind()
    unowned = connection.execute(
        sa.text("SELECT count(*) FROM sync_metadata WHERE user_id IS NULL")
    ).scalar_one()
    if unowned:
        assign_link_owners(connection, label=_LABEL, evidence_tables=EVIDENCE_TABLES)
    else:
        log.info("%s: every link already has an owner.", _LABEL)

    op.alter_column(
        "sync_metadata", "user_id", existing_type=sa.String(50), nullable=False
    )
    op.drop_index(_GLOBAL_INDEX, table_name="sync_metadata")


def downgrade() -> None:
    """Restore the global key, refusing an external id two owners hold."""
    shared = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT integration_source, external_id, "
                "count(DISTINCT user_id) AS owners FROM sync_metadata "
                "GROUP BY integration_source, external_id "
                "HAVING count(DISTINCT user_id) > 1 "
                "ORDER BY integration_source, external_id"
            )
        )
        .fetchall()
    )
    if shared:
        for row in shared:
            log.info(
                "%s: %s id %s is linked by %d owners.",
                _LABEL,
                row.integration_source,
                row.external_id,
                row.owners,
            )
        keys = ", ".join(
            f"{row.integration_source}:{row.external_id}" for row in shared
        )
        raise RuntimeError(
            f"{_LABEL} cannot be downgraded: {len(shared)} external ids are linked "
            f"by more than one owner ({keys}), which the global "
            f"(integration_source, external_id) key cannot hold. Remove all but "
            f"one owner's link for each first."
        )

    op.create_index(
        _GLOBAL_INDEX,
        "sync_metadata",
        ["integration_source", "external_id"],
        unique=True,
    )
    op.alter_column(
        "sync_metadata", "user_id", existing_type=sa.String(50), nullable=True
    )
