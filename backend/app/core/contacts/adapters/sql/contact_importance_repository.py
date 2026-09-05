"""SQL adapter for the shared contact-importance read.

**One statement for the whole batch.** The dashboard ranks every contact with an
important date in its window, so a per-contact read would be an N+1 on a path
that has to answer in one page load; an integration test counts the statements,
because functionally an N+1 is invisible — the answer is right either way and
only the number of round trips is wrong. The two aggregates are each computed in
their own ``LEFT JOIN LATERAL``, which keeps exactly one row per contact however
many journals or recorded changes it has. A scalar aggregate always returns a
row, so a contact with nothing attached comes back with zeros rather than
falling out of the result.

**The counts are computed in SQL, and this is not a behaviour change.** The
search indexer used to select every journal and every history row a contact had
ever had and count the recent ones in a Python loop. Every column involved —
``contacts.updated_at``, ``journals.created_at``, ``field_history.created_at`` —
is ``TIMESTAMP WITH TIME ZONE``, so comparing against a timezone-aware parameter
is exactly the comparison that loop performed; the loop's naive-datetime branch
was defensive and unreachable. The boundary stays inclusive (``>=``), which is
what the ranking has always used.

``GREATEST`` likewise reproduces the maximum the indexer took across the
contact's own ``updated_at``, its newest journal and its newest recorded change:
PostgreSQL's ``GREATEST`` ignores NULL arguments and returns NULL only when all
of them are NULL, and ``contacts.updated_at`` is ``NOT NULL``.

**The activity predicate is carried over verbatim, including its flaw.** It
matches the four child ``entity_type`` values against an ``entity_id`` drawn
from a ``UNION`` of all four child tables *without pairing a type to its table*,
so a ``contact_note`` row whose ``entity_id`` happens to equal one of this
contact's ``contact_method`` ids is counted. That is a real, small over-count in
today's ranking. This phase's acceptance criterion is that the search documents
do not change, so the predicate moves across unaltered and the correction is
recorded as a follow-up in the iteration document — a ranking change smuggled
inside an extraction is a change nobody reviewed.

**Not scoped by user**, because ``contacts`` has no owner column in this schema
and every other contacts repository is likewise unscoped. Adding a scope to the
journal half alone would change what the indexer counts, which is precisely what
this phase must not do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.core.contacts.models.importance import (
    IMPORTANCE_WINDOW_DAYS,
    ContactImportance,
)
from app.core.contacts.models.repositories import ContactImportanceRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

_IMPORTANCE_QUERY = text("""
    SELECT
        c.id,
        c.is_favourite,
        recent_journals.recent_count AS journal_count_30d,
        recent_activity.recent_count AS activity_count_30d,
        GREATEST(
            c.updated_at,
            recent_journals.latest_at,
            recent_activity.latest_at
        ) AS last_activity_at
    FROM contacts c
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (WHERE j.created_at >= :cutoff) AS recent_count,
            MAX(j.created_at) AS latest_at
        FROM journals j
        JOIN journal_contact_relationships jcr ON jcr.journal_id = j.id
        WHERE jcr.contact_id = c.id
    ) recent_journals ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (WHERE fh.created_at >= :cutoff) AS recent_count,
            MAX(fh.created_at) AS latest_at
        FROM field_history fh
        WHERE
            (fh.entity_type = 'contact' AND fh.entity_id = c.id)
            OR (fh.entity_type IN (
                    'contact_method', 'contact_address', 'contact_note', 'contact_tag'
                )
                AND fh.entity_id IN (
                    SELECT id FROM contact_methods WHERE contact_id = c.id
                    UNION
                    SELECT id FROM contact_addresses WHERE contact_id = c.id
                    UNION
                    SELECT id FROM contact_notes WHERE contact_id = c.id
                    UNION
                    SELECT tag_id FROM contact_tags WHERE contact_id = c.id
                ))
    ) recent_activity ON TRUE
    WHERE c.id = ANY(:contact_ids)
""")


class SqlContactImportanceRepository(ContactImportanceRepository):
    """Reads contact importance signals from PostgreSQL.

    Touches no search infrastructure, which is the point: the home dashboard
    orders its upcoming dates by these signals and must keep doing so while
    MeiliSearch is down.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        """Bind the read to a connection.

        Args:
            connection: The request's connection. The read opens no transaction
                of its own.
        """
        self.conn = connection

    async def for_contacts(
        self, contact_ids: Sequence[int], *, now: datetime | None = None
    ) -> dict[int, ContactImportance]:
        """The importance signals for each of ``contact_ids`` that exists.

        Args:
            contact_ids: The contacts to report on; an empty sequence short
                circuits without a round trip.
            now: The instant the window is measured back from, defaulting to the
                current time.

        Returns:
            A mapping from contact id to its signals, with unknown ids absent.
        """
        if not contact_ids:
            return {}

        anchor = now or datetime.now(UTC)
        result = await self.conn.execute(
            _IMPORTANCE_QUERY,
            {
                "cutoff": anchor - timedelta(days=IMPORTANCE_WINDOW_DAYS),
                "contact_ids": list(contact_ids),
            },
        )
        return {
            row.id: ContactImportance(
                contact_id=row.id,
                is_favourite=row.is_favourite,
                journal_count_30d=row.journal_count_30d,
                activity_count_30d=row.activity_count_30d,
                last_activity_at=row.last_activity_at,
            )
            for row in result
        }
