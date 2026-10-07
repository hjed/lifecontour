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

**The activity predicate is rendered from the contact history feed's own, not
transcribed from it.** ``contact_owned_history_predicate`` pairs each child
``entity_type`` with the single table its ``entity_id`` is drawn from. The
extraction that created this repository carried across a copy that tested the
type set and the id set *independently*, so a ``contact_note`` row numbered 5
counted for any contact owning a ``contact_method`` numbered 5 — an over-count
this read has now stopped making (#1396). Sharing the renderer is the point of
the fix: the bug was a second transcription of a predicate that was already
right elsewhere, and one renderer cannot drift from itself. The feed's further
branches — relationships, important dates, the summary, task links — stay with
the feed; whether those edits are *activity* is a separate question this change
does not answer.

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
from app.core.history.models import contact_owned_history_predicate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

# The rows that count as activity on the contact, correlated to ``c.id`` because
# the aggregate is computed inside a lateral over ``contacts``.
_ACTIVITY_PREDICATE = contact_owned_history_predicate(
    "c.id", table_alias="fh", indent=" " * 12
)

_IMPORTANCE_QUERY = text(f"""
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
            {_ACTIVITY_PREDICATE}
    ) recent_activity ON TRUE
    WHERE c.id = ANY(:contact_ids) AND c.user_id = :user_id
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
        self,
        contact_ids: Sequence[int],
        *,
        user_id: str,
        now: datetime | None = None,
    ) -> dict[int, ContactImportance]:
        """The importance signals for each of ``user_id``'s ``contact_ids``.

        Args:
            contact_ids: The contacts to report on; an empty sequence short
                circuits without a round trip.
            now: The instant the window is measured back from, defaulting to the
                current time.

        Returns:
            A mapping from contact id to its signals, with unknown ids and
            other users' contacts absent.
        """
        if not contact_ids:
            return {}

        anchor = now or datetime.now(UTC)
        result = await self.conn.execute(
            _IMPORTANCE_QUERY,
            {
                "cutoff": anchor - timedelta(days=IMPORTANCE_WINDOW_DAYS),
                "contact_ids": list(contact_ids),
                "user_id": user_id,
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
