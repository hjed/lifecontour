"""Dedupe bug-created duplicate contacts (ITER15-001 Phase 5)

Revision ID: 0092
Revises: 0091
Create Date: 2026-06-22 00:00:00.000000

Cleans up the duplicate contacts created by the Immich -> Google -> Immich
duplication loop before ``external_references`` is dropped (0093). The loop
produced pairs of the same person:

- **A (survivor)** — the original, email-less, Immich-origin contact carrying a
  full-precision birthday (Immich contacts are "name + birthday only"), linked by
  ``sync_metadata(immich, person)``.
- **B (source)** — an email-less duplicate re-imported by Google sync (the
  round-trip preserves the name and birthday), linked by
  ``sync_metadata(google, person)`` and carrying no Immich link.

This data migration identifies that shape and merges B into A using the **same
re-point SQL the live ``ContactMergeService`` uses** (relationships, journal links,
methods, addresses, notes, important dates, tags, top-level history, and the
canonical ``sync_metadata`` links), then deletes B. Orphaned ``sync_metadata``
links (whose internal entity no longer exists) are reconciled afterwards.

**Match discriminator.** Email-less is *not* exclusive to Immich (Google can also
import phone-only/empty contacts), so name alone would risk merging two genuinely
different people who share a name. A candidate pair must therefore share a
normalised name **and** an identical full-precision birthday — the attribute the
Immich-origin contact always carries and the round-trip preserves — so an accidental
merge would require two distinct people with the same exact name and birthday.

Safety (no over-merging, no silent loss):

- Only **unambiguous 1:1** name pairs merge; a name that maps to more than one
  survivor or source is skipped and logged (no guess).
- A **threshold guard** aborts the migration if the candidate count exceeds
  ``-x dedupe_max=<n>`` (default 1000) unless ``-x dedupe_force=true`` is given —
  a runaway count signals the match criteria are wrong and needs human review.
- ``-x dedupe_dry_run=true`` logs every pair it *would* merge and makes no changes.
- Every merge and every reconciled orphan is logged.

Idempotent: once B is merged into A, the survivor A still appears as an
email-less Immich-linked contact but now *also* holds the Google link and no
distinct same-name partner remains, so a re-run finds no pairs.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# Default ceiling on how many duplicate pairs may be merged in one run before the
# migration refuses to proceed without an explicit force flag.
_DEFAULT_MAX_PAIRS = 1000

# Normalised full name: trimmed, whitespace-collapsed, lower-cased — mirrors
# ``ContactNameMatcher`` normalisation so the SQL match is the conservative
# exact-name case.
# Build the unambiguous 1:1 survivor/source candidate pairs into a temp table.
# A = email-less contact with an Immich person link; B = email-less contact with a
# Google contact link and NO Immich link.
#
# Email-less is NOT exclusive to Immich (the Google inbound transformer can also
# create phone-only/empty contacts), so a shared normalised name alone is too weak
# a discriminator — two genuinely different people who happen to share a name could
# be merged. The bug only ever produces an Immich-origin contact, which carries a
# full-precision **birthday** (Immich contacts are "name + birthday only"), and the
# Immich->Google->Immich round-trip preserves it. So a candidate pair must share a
# normalised name AND an identical full-precision birthday — making a false merge
# require two distinct people with the same exact name and birthday. Pairs that
# don't corroborate on birthday are left for manual review rather than merged.
#
# A pair must additionally resolve to exactly one survivor and one source for that
# (name, birthday) key, and neither contact may appear on the other side of another
# pair (no chains).
_BUILD_CANDIDATES = sa.text(r"""
    CREATE TEMP TABLE _dedupe_candidates ON COMMIT DROP AS
    WITH immich_emailless AS (
        SELECT DISTINCT sm.internal_id AS contact_id,
               lower(regexp_replace(trim(
                   coalesce(c.first_name, '') || ' ' || coalesce(c.last_name, '')
               ), '\s+', ' ', 'g')) AS norm_name,
               bd.year AS bd_year, bd.month AS bd_month, bd.day AS bd_day
        FROM sync_metadata sm
        JOIN contacts c ON c.id = sm.internal_id
        JOIN contact_important_dates bd
          ON bd.contact_id = c.id
         AND bd.date_type = 'birthday'
         AND bd.precision = 'full'
         AND bd.year IS NOT NULL AND bd.month IS NOT NULL AND bd.day IS NOT NULL
        WHERE sm.integration_source = 'immich'
          AND sm.internal_entity_type = 'contact'
          AND sm.external_entity_type = 'person'
          AND sm.internal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods m
              WHERE m.contact_id = c.id AND m.method_type = 'email'
          )
    ),
    google_emailless AS (
        SELECT DISTINCT sm.internal_id AS contact_id,
               lower(regexp_replace(trim(
                   coalesce(c.first_name, '') || ' ' || coalesce(c.last_name, '')
               ), '\s+', ' ', 'g')) AS norm_name,
               bd.year AS bd_year, bd.month AS bd_month, bd.day AS bd_day
        FROM sync_metadata sm
        JOIN contacts c ON c.id = sm.internal_id
        JOIN contact_important_dates bd
          ON bd.contact_id = c.id
         AND bd.date_type = 'birthday'
         AND bd.precision = 'full'
         AND bd.year IS NOT NULL AND bd.month IS NOT NULL AND bd.day IS NOT NULL
        WHERE sm.integration_source = 'google'
          AND sm.internal_entity_type = 'contact'
          AND sm.external_entity_type = 'person'
          AND sm.internal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods m
              WHERE m.contact_id = c.id AND m.method_type = 'email'
          )
          AND NOT EXISTS (
              SELECT 1 FROM sync_metadata si
              WHERE si.integration_source = 'immich'
                AND si.internal_entity_type = 'contact'
                AND si.internal_id = sm.internal_id
          )
    ),
    pairs AS (
        SELECT a.contact_id AS survivor_id,
               b.contact_id AS source_id,
               a.norm_name, a.bd_year, a.bd_month, a.bd_day
        FROM immich_emailless a
        JOIN google_emailless b
          ON b.norm_name = a.norm_name
         AND b.bd_year = a.bd_year
         AND b.bd_month = a.bd_month
         AND b.bd_day = a.bd_day
         AND b.contact_id <> a.contact_id
        WHERE a.norm_name <> ''
    ),
    unambiguous AS (
        SELECT norm_name, bd_year, bd_month, bd_day
        FROM pairs
        GROUP BY norm_name, bd_year, bd_month, bd_day
        HAVING count(DISTINCT survivor_id) = 1
           AND count(DISTINCT source_id) = 1
    )
    SELECT p.survivor_id, p.source_id
    FROM pairs p
    JOIN unambiguous u
      ON u.norm_name = p.norm_name
     AND u.bd_year = p.bd_year
     AND u.bd_month = p.bd_month
     AND u.bd_day = p.bd_day
    WHERE p.survivor_id NOT IN (SELECT source_id FROM pairs)
      AND p.source_id NOT IN (SELECT survivor_id FROM pairs)
""")

# (name, birthday) keys that produced more than one survivor/source — recorded for
# the operator, never merged automatically.
_AMBIGUOUS = sa.text(r"""
    WITH immich_emailless AS (
        SELECT DISTINCT sm.internal_id AS contact_id,
               lower(regexp_replace(trim(
                   coalesce(c.first_name, '') || ' ' || coalesce(c.last_name, '')
               ), '\s+', ' ', 'g')) AS norm_name,
               bd.year AS bd_year, bd.month AS bd_month, bd.day AS bd_day
        FROM sync_metadata sm
        JOIN contacts c ON c.id = sm.internal_id
        JOIN contact_important_dates bd
          ON bd.contact_id = c.id
         AND bd.date_type = 'birthday'
         AND bd.precision = 'full'
         AND bd.year IS NOT NULL AND bd.month IS NOT NULL AND bd.day IS NOT NULL
        WHERE sm.integration_source = 'immich'
          AND sm.internal_entity_type = 'contact'
          AND sm.external_entity_type = 'person'
          AND sm.internal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods m
              WHERE m.contact_id = c.id AND m.method_type = 'email'
          )
    ),
    google_emailless AS (
        SELECT DISTINCT sm.internal_id AS contact_id,
               lower(regexp_replace(trim(
                   coalesce(c.first_name, '') || ' ' || coalesce(c.last_name, '')
               ), '\s+', ' ', 'g')) AS norm_name,
               bd.year AS bd_year, bd.month AS bd_month, bd.day AS bd_day
        FROM sync_metadata sm
        JOIN contacts c ON c.id = sm.internal_id
        JOIN contact_important_dates bd
          ON bd.contact_id = c.id
         AND bd.date_type = 'birthday'
         AND bd.precision = 'full'
         AND bd.year IS NOT NULL AND bd.month IS NOT NULL AND bd.day IS NOT NULL
        WHERE sm.integration_source = 'google'
          AND sm.internal_entity_type = 'contact'
          AND sm.external_entity_type = 'person'
          AND sm.internal_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM contact_methods m
              WHERE m.contact_id = c.id AND m.method_type = 'email'
          )
          AND NOT EXISTS (
              SELECT 1 FROM sync_metadata si
              WHERE si.integration_source = 'immich'
                AND si.internal_entity_type = 'contact'
                AND si.internal_id = sm.internal_id
          )
    ),
    pairs AS (
        SELECT a.contact_id AS survivor_id, b.contact_id AS source_id,
               a.norm_name, a.bd_year, a.bd_month, a.bd_day
        FROM immich_emailless a
        JOIN google_emailless b
          ON b.norm_name = a.norm_name
         AND b.bd_year = a.bd_year
         AND b.bd_month = a.bd_month
         AND b.bd_day = a.bd_day
         AND b.contact_id <> a.contact_id
        WHERE a.norm_name <> ''
    )
    SELECT norm_name, bd_year, bd_month, bd_day,
           count(DISTINCT survivor_id) AS survivors,
           count(DISTINCT source_id) AS sources
    FROM pairs
    GROUP BY norm_name, bd_year, bd_month, bd_day
    HAVING count(DISTINCT survivor_id) > 1 OR count(DISTINCT source_id) > 1
""")

# --- Per-pair re-point statements ---
# The entity re-points are byte-for-byte the SQL the live ``ContactMergeService``
# runs (relationships / journal links / methods / addresses / notes / important
# dates / tags / top-level history). The final ``sync_metadata`` link block is
# functionally equivalent to ``SyncMetadataRepository.repoint_contact_links`` —
# survivor-wins on a same-service collision — but it has nothing to return: an
# offline migration fires no ``ContactMerged`` event, and the bug shape (survivor
# = immich-only, source = google-only) never collides anyway.

_REPOINT_STATEMENTS = (
    # Relationships: drop inter-pair self-loops, then dedupe + re-point both sides.
    """
    DELETE FROM contact_relationships
    WHERE to_user = false
      AND (
          (from_contact_id = :source_id AND to_contact_id = :survivor_id)
          OR (from_contact_id = :survivor_id AND to_contact_id = :source_id)
      )
    """,
    """
    DELETE FROM contact_relationships src
    WHERE src.from_contact_id = :source_id
      AND src.to_user = false
      AND EXISTS (
          SELECT 1 FROM contact_relationships tgt
          WHERE tgt.from_contact_id = :survivor_id
            AND tgt.to_user = false
            AND tgt.to_contact_id = src.to_contact_id
            AND tgt.relationship_type = src.relationship_type
      )
    """,
    """
    DELETE FROM contact_relationships src
    WHERE src.from_contact_id = :source_id
      AND src.to_user = true
      AND EXISTS (
          SELECT 1 FROM contact_relationships tgt
          WHERE tgt.from_contact_id = :survivor_id
            AND tgt.to_user = true
            AND tgt.relationship_type = src.relationship_type
      )
    """,
    """
    UPDATE contact_relationships
    SET from_contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE from_contact_id = :source_id
    """,
    """
    DELETE FROM contact_relationships src
    WHERE src.to_contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_relationships tgt
          WHERE tgt.to_contact_id = :survivor_id
            AND tgt.from_contact_id = src.from_contact_id
            AND tgt.relationship_type = src.relationship_type
      )
    """,
    """
    UPDATE contact_relationships
    SET to_contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE to_contact_id = :source_id
    """,
    # Journal links: dedupe on the composite PK, then re-point.
    """
    DELETE FROM journal_contact_relationships src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM journal_contact_relationships tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.journal_id = src.journal_id
            AND tgt.relationship_type = src.relationship_type
      )
    """,
    """
    UPDATE journal_contact_relationships
    SET contact_id = :survivor_id
    WHERE contact_id = :source_id
    """,
    # Methods: collapse exact duplicates, demote colliding primaries, re-point.
    """
    DELETE FROM contact_methods src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_methods tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.method_type = src.method_type
            AND tgt.value = src.value
      )
    """,
    """
    UPDATE contact_methods src
    SET is_primary = false, updated_at = CURRENT_TIMESTAMP
    WHERE src.contact_id = :source_id
      AND src.is_primary = true
      AND EXISTS (
          SELECT 1 FROM contact_methods tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.method_type = src.method_type
            AND tgt.is_primary = true
      )
    """,
    """
    UPDATE contact_methods
    SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE contact_id = :source_id
    """,
    # Addresses: collapse exact duplicates, demote colliding primaries, re-point.
    """
    DELETE FROM contact_addresses src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_addresses tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.street_line_1 = src.street_line_1
            AND tgt.country_code = src.country_code
            AND tgt.street_line_2 IS NOT DISTINCT FROM src.street_line_2
            AND tgt.locality IS NOT DISTINCT FROM src.locality
            AND tgt.region IS NOT DISTINCT FROM src.region
            AND tgt.postal_code IS NOT DISTINCT FROM src.postal_code
            AND tgt.label IS NOT DISTINCT FROM src.label
      )
    """,
    """
    UPDATE contact_addresses src
    SET is_primary = false, updated_at = CURRENT_TIMESTAMP
    WHERE src.contact_id = :source_id
      AND src.is_primary = true
      AND EXISTS (
          SELECT 1 FROM contact_addresses tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.is_primary = true
      )
    """,
    """
    UPDATE contact_addresses
    SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE contact_id = :source_id
    """,
    # Notes: collapse duplicate content, re-point.
    """
    DELETE FROM contact_notes src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_notes tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.content = src.content
      )
    """,
    """
    UPDATE contact_notes
    SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE contact_id = :source_id
    """,
    # Important dates: collapse duplicates, drop colliding birthday, re-point.
    """
    DELETE FROM contact_important_dates src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_important_dates tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.date_type = src.date_type
            AND tgt.precision = src.precision
            AND tgt.year IS NOT DISTINCT FROM src.year
            AND tgt.month IS NOT DISTINCT FROM src.month
            AND tgt.day IS NOT DISTINCT FROM src.day
            AND tgt.custom_date_type_id IS NOT DISTINCT FROM src.custom_date_type_id
      )
    """,
    """
    DELETE FROM contact_important_dates src
    WHERE src.contact_id = :source_id
      AND src.date_type = 'birthday'
      AND EXISTS (
          SELECT 1 FROM contact_important_dates tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.date_type = 'birthday'
      )
    """,
    """
    UPDATE contact_important_dates
    SET contact_id = :survivor_id, updated_at = CURRENT_TIMESTAMP
    WHERE contact_id = :source_id
    """,
    # Tags: dedupe on the composite PK, then re-point.
    """
    DELETE FROM contact_tags src
    WHERE src.contact_id = :source_id
      AND EXISTS (
          SELECT 1 FROM contact_tags tgt
          WHERE tgt.contact_id = :survivor_id
            AND tgt.tag_id = src.tag_id
      )
    """,
    """
    UPDATE contact_tags
    SET contact_id = :survivor_id
    WHERE contact_id = :source_id
    """,
    # Top-level (entity_type='contact') history: copy-then-delete, dedup index safe.
    """
    WITH moved AS (
        INSERT INTO field_history
            (entity_type, entity_id, field_name, old_value, new_value,
             changed_by, source, event_id, created_at)
        SELECT entity_type, :survivor_id, field_name, old_value, new_value,
               changed_by, source, event_id, created_at
        FROM field_history
        WHERE entity_type = 'contact' AND entity_id = :source_id
        ON CONFLICT (event_id, entity_type, entity_id, field_name) DO NOTHING
        RETURNING 1
    ),
    deleted AS (
        DELETE FROM field_history
        WHERE entity_type = 'contact' AND entity_id = :source_id
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM moved), (SELECT count(*) FROM deleted)
    """,
    # Canonical links: carry over non-colliding source links to the survivor...
    """
    UPDATE sync_metadata s
    SET internal_id = :survivor_id, updated_at = now()
    WHERE s.internal_entity_type = 'contact'
      AND s.internal_id = :source_id
      AND NOT EXISTS (
          SELECT 1 FROM sync_metadata t
          WHERE t.internal_entity_type = 'contact'
            AND t.internal_id = :survivor_id
            AND t.integration_source = s.integration_source
      )
    """,
    # ...then drop the remaining source links (collisions: survivor's link wins).
    """
    DELETE FROM sync_metadata
    WHERE internal_entity_type = 'contact' AND internal_id = :source_id
    """,
    # Finally remove the now-empty source contact (sub-entities cascade).
    """
    DELETE FROM contacts WHERE id = :source_id
    """,
)

# Reconcile links left orphaned by this or earlier cleanup: a contact/journal link
# whose internal entity no longer exists. UUID-keyed links (internal_id NULL) and
# sources without a backing table are left untouched.
_RECONCILE_CONTACT_ORPHANS = sa.text("""
    DELETE FROM sync_metadata sm
    WHERE sm.internal_entity_type = 'contact'
      AND sm.internal_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.id = sm.internal_id)
""")

_RECONCILE_JOURNAL_ORPHANS = sa.text("""
    DELETE FROM sync_metadata sm
    WHERE sm.internal_entity_type = 'journal'
      AND sm.internal_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM journals j WHERE j.id = sm.internal_id)
""")


def _x_args() -> dict[str, str]:
    """Read alembic ``-x key=value`` arguments (empty when none supplied)."""
    return context.get_x_argument(as_dictionary=True)


def _flag(args: dict[str, str], name: str) -> bool:
    return args.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _merge_pair(bind: sa.engine.Connection, survivor_id: int, source_id: int) -> None:
    """Merge ``source_id`` into ``survivor_id`` using the live merge's re-point SQL."""
    params = {"survivor_id": survivor_id, "source_id": source_id}
    for statement in _REPOINT_STATEMENTS:
        bind.execute(sa.text(statement), params)


def upgrade() -> None:
    """Merge bug-created duplicate contacts and reconcile orphaned links."""
    bind = op.get_bind()
    args = _x_args()
    dry_run = _flag(args, "dedupe_dry_run")
    force = _flag(args, "dedupe_force")
    try:
        max_pairs = int(args.get("dedupe_max", _DEFAULT_MAX_PAIRS))
    except ValueError:
        max_pairs = _DEFAULT_MAX_PAIRS

    bind.execute(_BUILD_CANDIDATES)
    pairs = bind.execute(
        sa.text(
            "SELECT survivor_id, source_id FROM _dedupe_candidates "
            "ORDER BY survivor_id, source_id"
        )
    ).fetchall()

    for row in bind.execute(_AMBIGUOUS).fetchall():
        log.warning(
            "link-consolidation dedupe: skipping ambiguous name '%s' "
            "(birthday %s-%s-%s; %s survivors, %s sources) — needs manual review",
            row.norm_name,
            row.bd_year,
            row.bd_month,
            row.bd_day,
            row.survivors,
            row.sources,
        )

    log.info(
        "link-consolidation dedupe: %d unambiguous duplicate pair(s) identified",
        len(pairs),
    )

    if len(pairs) > max_pairs and not force:
        raise RuntimeError(
            f"link-consolidation dedupe: {len(pairs)} candidate pairs exceed the "
            f"safety threshold ({max_pairs}). Review the match criteria, then re-run "
            f"with -x dedupe_force=true (and/or -x dedupe_max=<n>) once verified."
        )

    if dry_run:
        for row in pairs:
            log.info(
                "[dry-run] would merge source contact %s into survivor %s",
                row.source_id,
                row.survivor_id,
            )
        log.info("[dry-run] no changes applied; orphan reconciliation skipped")
        return

    for row in pairs:
        _merge_pair(bind, row.survivor_id, row.source_id)
        log.info(
            "link-consolidation dedupe: merged source contact %s into survivor %s",
            row.source_id,
            row.survivor_id,
        )

    contact_orphans = bind.execute(_RECONCILE_CONTACT_ORPHANS).rowcount
    journal_orphans = bind.execute(_RECONCILE_JOURNAL_ORPHANS).rowcount
    log.info(
        "link-consolidation dedupe: reconciled %d orphaned contact link(s) and "
        "%d orphaned journal link(s)",
        contact_orphans,
        journal_orphans,
    )


def downgrade() -> None:
    """Irreversible data cleanup.

    The merge collapses duplicate contacts and their links and deletes the source
    rows; the pre-merge state cannot be reconstructed. Downgrade is a no-op so the
    revision can still be stepped over without error.
    """
    log.info("0092 dedupe is a data migration; downgrade is a no-op (irreversible)")
