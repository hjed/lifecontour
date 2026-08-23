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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


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
