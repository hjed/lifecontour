"""Find the site's one user for a migration that gives an unowned table an owner.

A site supports exactly one person, but tables such as ``contacts`` were created
without a ``user_id``. A migration that adds one has to assign every existing
row, and the owner is derived from the data rather than configured: it is the
single distinct ``user_id`` across the tables that already record one. Each
migration passes its own literal tuple of those *evidence* tables, so a revision
keeps meaning the same thing however later schemas move on.

The decision, logged step by step through Alembic's own logger:

- an operator override (``alembic -x <name>=<user_id>``) always wins;
- exactly one real owner -> that owner;
- no real owner, only synthetic ones -> the synthetic owner, preferring
  ``dev-user`` (the ``DISABLE_AUTH`` identity of local dev, CI and e2e) when
  ``debug-client`` is also present — ``debug-client`` can no longer be produced,
  so a database holding both is a legacy development one;
- no evidence at all, or more than one real owner -> ``RuntimeError`` naming
  what was found and the override that resolves it.

Migration ``0106`` explains where the two synthetic identities came from. This
module is shared by several revisions, so treat its behaviour as frozen once a
revision depends on it: change it only by adding, never by redefining.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context

log = logging.getLogger("alembic.runtime.migration")

SYNTHETIC_OWNER_IDS = ("debug-client", "dev-user")
PREFERRED_SYNTHETIC_OWNER = "dev-user"


def x_argument(name: str) -> str | None:
    """Return the ``-x name=value`` argument, or ``None`` when absent or blank."""
    value = context.get_x_argument(as_dictionary=True).get(name, "").strip()
    return value or None


def owner_counts(
    connection: sa.Connection, evidence_tables: Sequence[str]
) -> dict[str, int]:
    """Return ``{user_id: row_count}`` summed across ``evidence_tables``."""
    union = " UNION ALL ".join(
        f"SELECT user_id FROM {table} WHERE user_id IS NOT NULL"
        for table in evidence_tables
    )
    rows = connection.execute(
        sa.text(f"SELECT user_id, count(*) AS n FROM ({union}) owners GROUP BY user_id")  # noqa: S608 - table names come from the calling migration's literal tuple
    ).fetchall()
    return {str(row.user_id): int(row.n) for row in rows}


def _describe(counts: dict[str, int]) -> str:
    return ", ".join(
        f"{owner!r} ({count} rows)" for owner, count in sorted(counts.items())
    )


def derive_owner(
    connection: sa.Connection,
    *,
    evidence_tables: Sequence[str],
    label: str,
    override_name: str,
) -> str:
    """Return the one user every unowned row should be assigned to.

    ``label`` prefixes every log line and error (the revision number);
    ``override_name`` is the ``-x`` argument an operator passes to choose the
    owner when the data cannot.
    """
    override = x_argument(override_name)
    if override is not None:
        log.info("%s: owner given by -x %s: %r.", label, override_name, override)
        return override

    counts = owner_counts(connection, evidence_tables)
    real = {o: n for o, n in counts.items() if o not in SYNTHETIC_OWNER_IDS}
    synthetic = {o: n for o, n in counts.items() if o in SYNTHETIC_OWNER_IDS}
    hint = f"Pass the owner explicitly with `alembic -x {override_name}=<user_id>`."

    if len(real) == 1:
        owner = next(iter(real))
        log.info("%s: the site's owner is %r (%s).", label, owner, _describe(counts))
        return owner

    if len(real) > 1:
        raise RuntimeError(
            f"{label} cannot choose an owner: this site should have exactly one "
            f"user but the data holds {len(real)} — {_describe(real)}. {hint}"
        )

    if synthetic:
        owner = (
            PREFERRED_SYNTHETIC_OWNER
            if PREFERRED_SYNTHETIC_OWNER in synthetic
            else next(iter(synthetic))
        )
        log.info(
            "%s: only synthetic owners present (%s); assigning %r.",
            label,
            _describe(synthetic),
            owner,
        )
        return owner

    raise RuntimeError(
        f"{label} cannot choose an owner: no table records a user "
        f"(checked {', '.join(evidence_tables)}). {hint}"
    )


def assign_unowned(
    connection: sa.Connection, table: str, owner: str, label: str
) -> None:
    """Give every row of ``table`` whose ``user_id`` is NULL to ``owner``."""
    result = connection.execute(
        sa.text(f"UPDATE {table} SET user_id = :owner WHERE user_id IS NULL"),  # noqa: S608 - table name comes from the calling migration
        {"owner": owner},
    )
    log.info("%s: %s: %d rows assigned to %r.", label, table, result.rowcount, owner)
