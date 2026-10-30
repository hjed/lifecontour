"""Whether the backend has migrated calendar links to hold a synced base (#1899).

Migration 0143 adds ``journal_external_event_links.reference_data``, and runs
when the backend starts. The worker deploys independently, so it can run
against a database that does not have the column yet, where naming it fails
every calendar pull and push. Until the column is there, the worker neither
reads nor writes a base, and pushes every field as it did before.

Remove this once every deployment has run 0143.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class _Readiness:
    ready: bool = False


# Once the column exists it stays, so a "yes" is remembered for the process.
READINESS = _Readiness()


async def link_reference_data_ready(session: AsyncSession) -> bool:
    """Whether ``journal_external_event_links.reference_data`` exists yet."""
    if not READINESS.ready:
        result = await session.execute(
            text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'journal_external_event_links'
                  AND column_name = 'reference_data'
            """)
        )
        READINESS.ready = result.first() is not None
    return READINESS.ready
