"""reassign rows owned by a synthetic identity to the site's real user

Revision ID: 0106
Revises: 0105
Create Date: 2026-08-23 00:00:00.000000

Two hard-coded strings have owned real rows over this project's life, neither of
them a person:

- ``'debug-client'`` — FastMCP's ``DebugTokenVerifier`` supplies no identity
  claims and defaults ``client_id`` to this value. From ``09ac9cce2c``
  (2026-03-20), when MCP moved from session-cookie auth to the OAuth proxy,
  ``session_user_from_claims`` fell through ``sub -> id -> client_id`` and every
  MCP write was attributed to it.
- ``'dev-user'`` — the mock user REST returns whenever ``DISABLE_AUTH`` is set,
  since ``11675d6f1a`` (2025-06-20). Anything created through the UI while the
  deployment ran with auth disabled belongs to it.

Rows owned by either are unreachable from the signed-in user: every owner-scoped
endpoint filters on ``user_id`` in SQL, so they answer 404. That is the bug this
revision repairs — the journal activity feed 404ing on MCP-created journals — and
nothing has ever rewritten these values before.

A site supports exactly one user, so the target owner is derived from the data
rather than configured: it is the single distinct ``user_id`` across the repaired
tables that is not one of the constants above.

- **no synthetic rows** — nothing to do (fresh installs).
- **no real owner** — nothing to move rows *to*. This is local dev, CI and e2e,
  where ``'dev-user'`` is the legitimate owner of everything; leave it alone.
- **exactly one real owner** — reassign every synthetic-owned row to it.
- **more than one** — refuse. It cannot legitimately happen here, and picking
  one would merge two people's data; the error names the owners instead.

A unique constraint spanning ``user_id`` (``outdoor_activity_dismissals``,
``strava_athlete_mappings``) could in principle collide if both owners held the
same key. That aborts the migration loudly rather than dropping a row, which is
the right trade for data that cannot be reconstructed.

``journal_daily_summaries`` is deliberately *not* repaired despite having a
``user_id``: it is regenerable cache, and its ``UNIQUE (user_id, summary_date)``
makes a collision likely rather than theoretical. Integration credential and
settings tables (``user_*_auth``, ``user_settings``, ``snipeit_settings``,
``sync_jobs``, ``calendar_sync_tokens``, ``pending_entity_mappings``) are also
out of scope — they are only ever written by the authenticated REST user.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0106"
down_revision: str | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Alembic's own logger, so the repair narrates itself in the migration output.
log = logging.getLogger("alembic.runtime.migration")

# Identities that are not people. See the module docstring for where each came
# from. Kept literal rather than imported from ``app`` so this revision keeps
# meaning the same thing however the application code moves on.
SYNTHETIC_OWNER_IDS = ("debug-client", "dev-user")

# User-owned content tables written by the MCP and REST surfaces. ``routes`` is
# absent on purpose: it carries no ``user_id`` and is owned through its journal.
REPAIRED_TABLES = (
    "journals",
    "calendars",
    "gear_items",
    "journal_series",
    "activity_templates",
    "tasks",
    "outdoor_activity_dismissals",
    "journal_review_items",
    "strava_athlete_mappings",
)


def _owner_counts(connection: sa.Connection) -> dict[str, int]:
    """Return ``{user_id: row_count}`` summed across the repaired tables."""
    union = " UNION ALL ".join(
        f"SELECT user_id FROM {table}" for table in REPAIRED_TABLES
    )
    rows = connection.execute(
        sa.text(f"SELECT user_id, count(*) AS n FROM ({union}) owners GROUP BY user_id")  # noqa: S608 - table names come from the constant tuple above
    ).fetchall()
    return {str(row.user_id): int(row.n) for row in rows}


def _describe(counts: dict[str, int]) -> str:
    return ", ".join(
        f"{owner!r} ({count} rows)" for owner, count in sorted(counts.items())
    )


def upgrade() -> None:
    """Hand every synthetic-owned row to the site's real user."""
    connection = op.get_bind()
    counts = _owner_counts(connection)

    synthetic = {
        owner: count for owner, count in counts.items() if owner in SYNTHETIC_OWNER_IDS
    }
    if not synthetic:
        log.info("0106: no rows owned by a synthetic identity; nothing to repair.")
        return

    candidates = {
        owner: count
        for owner, count in counts.items()
        if owner not in SYNTHETIC_OWNER_IDS
    }

    if not candidates:
        # Every row belongs to a synthetic owner: this is a development, CI or
        # e2e database where that is the real identity. Moving them would be
        # wrong, and there is nowhere to move them to.
        log.info(
            "0106: only synthetic owners present (%s); leaving them alone.",
            _describe(synthetic),
        )
        return

    if len(candidates) > 1:
        raise RuntimeError(
            "0106 cannot choose an owner: this site should have exactly one "
            f"user but the data holds {len(candidates)} — {_describe(candidates)}. "
            f"Rows to repair: {_describe(synthetic)}. Resolve the ownership "
            "manually, then re-run."
        )

    target = next(iter(candidates))
    log.info("0106: reassigning %s to %r.", _describe(synthetic), target)

    for table in REPAIRED_TABLES:
        result = connection.execute(
            sa.text(  # noqa: S608 - table names come from the constant tuple above
                f"UPDATE {table} SET user_id = :target "
                "WHERE user_id = ANY(:synthetic_ids)"
            ),
            {"target": target, "synthetic_ids": list(SYNTHETIC_OWNER_IDS)},
        )
        if result.rowcount:
            log.info("0106:   %s: %d rows reassigned.", table, result.rowcount)


def downgrade() -> None:
    """Intentionally a no-op.

    Once reassigned, a repaired row is indistinguishable from one that always
    belonged to that user — the ownership it used to carry is not recorded
    anywhere. Handing rows back to a synthetic identity by guesswork would
    re-orphan data the upgrade rescued, so this reverses nothing.
    """
