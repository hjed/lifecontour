"""Bumping a journal's ``updated_at`` when part of the journal changes elsewhere.

``GET /api/journals/{id}`` represents the journal *aggregate* — its own fields
plus its types, type-specific data, tags and contact relationships — and the
entity-tag handed out with that representation is derived from
``journals.updated_at``. A write that changes any of those child rows without
bumping the parent leaves the tag naming a version that no longer describes
what a client would read, so a conditional write would be accepted despite a
concurrent change it was meant to catch. That matters most for the MCP
composite update, which *replaces* types, tags and relationships under the
caller's precondition.

``now()`` is the transaction timestamp, so touching a journal that the same
transaction already wrote is a no-op in value — a composite update that bumps
the row once and touches it again lands on the same timestamp.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def lock_journal(conn: AsyncConnection, journal_id: int) -> None:
    """Take a journal's row lock before writing any of its child rows.

    Every path that writes journal child data ends by touching the parent, and
    a conditional write takes the parent's lock *first* (see
    ``lock_and_get_updated_at``). Without this, the two orders invert: the
    conditional write holds the parent and wants the child, while a plain child
    write holds the child and wants the parent, and PostgreSQL breaks the cycle
    by aborting one of them with a deadlock. Locking the parent up front makes
    every writer take the locks in the same order, so they queue instead.

    Taking the lock here also means the closing ``touch_journal`` needs no lock
    of its own — it already holds one.
    """
    await conn.execute(
        text("SELECT 1 FROM journals WHERE id = :journal_id FOR UPDATE"),
        {"journal_id": journal_id},
    )


async def touch_journals_holding_tag(conn: AsyncConnection, tag_id: UUID) -> None:
    """Mark every journal carrying a tag as changed, locking them first.

    For the bulk assignment rewrites — merging a tag into another, or deleting
    one — where the journals affected are not known to the caller and the
    assignment rows are about to stop pointing at this tag. Runs *before* that
    rewrite, while the assignments still name the journals to touch, and takes
    the parent locks ahead of the child writes for the reason
    :func:`lock_journal` explains.
    """
    await conn.execute(
        text(
            """
            UPDATE journals SET updated_at = now()
            WHERE id IN (
                SELECT journal_id FROM journal_tag_assignments WHERE tag_id = :tag_id
            )
            """
        ),
        {"tag_id": tag_id},
    )


async def touch_journal(conn: AsyncConnection, journal_id: int) -> None:
    """Record that a journal changed, without changing its own columns.

    Silently does nothing when the journal does not exist: every caller writes
    a child row keyed to a real journal, and a missing parent is that write's
    problem to report, not this helper's.
    """
    await conn.execute(
        text("UPDATE journals SET updated_at = now() WHERE id = :journal_id"),
        {"journal_id": journal_id},
    )
