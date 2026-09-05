"""relocate legacy imported all-day events onto local midnight

Revision ID: 0109
Revises: 0108
Create Date: 2026-09-05 00:00:00.000000

``journals.event_date_range_start/end`` hold the UTC instant of **local**
midnight in the zone the event is anchored in, and
``journal_calendar_info.timezone`` records that zone. Midnight on 5 September
in Sydney is therefore ``2026-09-04T14:00Z``.

The Google inbound sync did not follow that until #1385. It parsed an all-day
event's bare date as ``datetime(y, m, d, tzinfo=UTC)`` and stored no zone, so
every all-day event imported before then sits at **UTC** midnight with
``timezone IS NULL``. Those rows:

- read on the right day for a user east of UTC and a day **early** for a user
  west of it, in the calendar view and the journals list, which group on the
  raw instant;
- push back to Google a day early on the next update for a user west of UTC,
  because the outbound path falls back to the user's configured zone for an
  all-day row that records none — which is the bug LOCAL-137 reported.

This revision moves them onto the convention: each bound is re-read as a UTC
date and re-anchored at midnight of that same date in the user's configured
zone, and the zone is recorded on the row.

**Which rows.** All-day, no recorded zone, and an external link with
``sync_capability = 'bidirectional'`` — the shape only an inbound sync
produces. Two further conditions are not in that description but are part of
what "legacy" means:

- **Both bounds must be exactly 00:00:00 UTC.** An app-created all-day row
  whose zone was cleared (``EventTypeEditor`` sends ``e.target.value || null``)
  matches every other predicate, but its instant is *already* local midnight;
  moving it would push it a day out. For a user at a zero offset the condition
  admits rows the move then leaves unchanged, which is harmless.
- **The zone must be one PostgreSQL resolves.** ``timezone`` is an
  unconstrained string and ``AT TIME ZONE`` *raises* on a name it does not
  know, which aborts the whole statement — so ``agenda_repository`` already
  resolves the column through ``pg_timezone_names`` before using it. Writing
  only names that catalogue holds keeps those reads from breaking on a
  repaired row.

A ``user_settings`` row is not guaranteed, so the zone is taken over a LEFT
JOIN with the same ``'UTC'`` default the application itself falls back to.
The move is then a no-op, but recording the zone still matters: without one
the row inherits whatever zone the user configures *later*, and would start
reading a day early the moment that is a negative offset.

Re-anchoring is done from each bound's own **date**, not by shifting both by a
single offset: an all-day event spanning a clock change takes a different
offset at each end (31 October to 2 November in New York is -04:00 then
-05:00), and a fixed delta would leave the far end an hour off midnight.

**No re-push, and no outbox event.** Google already holds the correct dates —
only this side's representation was wrong — so nothing needs to be sent back.
Raw SQL keeps ``journals.updated_at`` untouched (its ``onupdate`` is
SQLAlchemy-side and the schema carries no triggers), so the repair raises no
outbox event and starts no sync.

**Operational note.** The MeiliSearch journal document carries
``event_date_range_start``/``event_date_range_end`` as sortable and filterable
fields, and because this revision deliberately writes no outbox event the
index keeps the old instants until each journal is next written. Run
``POST /api/search/reindex`` for journals after deploying. It is not urgent:
the staleness is a few hours of sort order on rows whose indexed values were
equally wrong before.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0109"
down_revision: str | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Alembic's own logger, so the repair narrates itself in the migration output.
log = logging.getLogger("alembic.runtime.migration")

# The shape of a row the legacy inbound sync left behind. Shared by the repair
# and by the count of rows it has to decline, so the two cannot drift apart.
_LEGACY_PREDICATES = """
        jci.is_all_day
    AND jci.timezone IS NULL
    AND (j.event_date_range_start AT TIME ZONE 'UTC')::time = TIME '00:00'
    AND (j.event_date_range_end AT TIME ZONE 'UTC')::time = TIME '00:00'
    AND EXISTS (
        SELECT 1 FROM journal_external_event_links l
        WHERE l.journal_id = j.id AND l.sync_capability = 'bidirectional'
    )
"""

# Journals of the legacy shape whose zone PostgreSQL cannot resolve. They keep
# the instants and the NULL they have today: read as UTC, which is what they
# are, exactly as before this revision.
_UNRESOLVABLE_ZONES = f"""
    SELECT COALESCE(us.timezone, 'UTC') AS tz, count(*) AS n
    FROM journals j
    JOIN journal_calendar_info jci ON jci.journal_id = j.id
    LEFT JOIN user_settings us ON us.user_id = j.user_id
    WHERE {_LEGACY_PREDICATES}
      AND NOT EXISTS (
          SELECT 1 FROM pg_timezone_names ptz
          WHERE ptz.name = COALESCE(us.timezone, 'UTC')
      )
    GROUP BY tz
"""

# One statement, because once the bounds move they no longer match the
# 00:00 UTC predicate and the journal_calendar_info update could not find them
# again. The data-modifying CTE runs exactly once and to completion whether or
# not the primary query reads its output.
_RELOCATE = f"""
    WITH legacy AS (
        SELECT j.id AS journal_id, COALESCE(us.timezone, 'UTC') AS tz
        FROM journals j
        JOIN journal_calendar_info jci ON jci.journal_id = j.id
        LEFT JOIN user_settings us ON us.user_id = j.user_id
        JOIN pg_timezone_names ptz ON ptz.name = COALESCE(us.timezone, 'UTC')
        WHERE {_LEGACY_PREDICATES}
    ),
    moved AS (
        UPDATE journals j
        SET event_date_range_start =
                ((j.event_date_range_start AT TIME ZONE 'UTC')::date + TIME '00:00')
                AT TIME ZONE legacy.tz,
            event_date_range_end =
                ((j.event_date_range_end AT TIME ZONE 'UTC')::date + TIME '00:00')
                AT TIME ZONE legacy.tz
        FROM legacy
        WHERE j.id = legacy.journal_id
        RETURNING j.id
    )
    UPDATE journal_calendar_info jci
    SET timezone = legacy.tz
    FROM legacy
    WHERE jci.journal_id = legacy.journal_id
"""


def upgrade() -> None:
    """Move legacy imported all-day events onto local midnight."""
    connection = op.get_bind()

    for row in connection.execute(sa.text(_UNRESOLVABLE_ZONES)).fetchall():
        log.warning(
            "0109: leaving %d all-day journal(s) alone — PostgreSQL does not "
            "recognise the configured timezone %r.",
            int(row.n),
            str(row.tz),
        )

    result = connection.execute(sa.text(_RELOCATE))
    if result.rowcount:
        log.info(
            "0109: %d all-day journal(s) moved to local midnight.", result.rowcount
        )
    else:
        log.info("0109: no legacy all-day journals to move.")


def downgrade() -> None:
    """Intentionally a no-op.

    A repaired row is indistinguishable from one the current sync wrote
    correctly: both are local midnight with the zone recorded. Pushing rows
    back to UTC midnight by guesswork would re-break the ones that were never
    broken, so this reverses nothing.
    """
