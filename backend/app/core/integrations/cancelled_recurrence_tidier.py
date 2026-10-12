"""Carry out the keep-next rule on one recurrence, after a cancellation.

:mod:`cancelled_recurrence` decides which cancelled occurrences are
continuations of a run. This module loads a recurrence's occurrences, asks it,
and deletes the continuations nobody has added to. A continuation the user
has added to stays, marked cancelled like the rest of its run.

What counts as "added to":

- the deletion protection facts (children, tags, manual contacts, type data,
  routes);
- another calendar that still holds the event;
- a change in the journal's history made in the app or through MCP;
- a task anchored to the journal, which the delete guard refuses.

Each deletion runs in its own SAVEPOINT, so one that fails takes back only
its own writes and the rest of the recurrence is still tidied.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncStatus,
)
from core_shared.models.journals import JournalHasAnchoredTasksError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SeriesLinkedJournal,
    SqlJournalEventLinkRepository,
)
from app.core.integrations.cancelled_recurrence import (
    CancelledInstanceVerdict,
    RecurrenceInstance,
    affected_by_cancel,
    plan_cancelled_recurrence,
)
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.unit_of_work import savepoint

logger = structlog.get_logger()


@dataclass(frozen=True)
class TidyOutcome:
    """What tidying one recurrence did."""

    deleted: frozenset[int]
    errors: int


def _as_instance(linked: SeriesLinkedJournal) -> RecurrenceInstance | None:
    if linked.event_date_range_start is None:
        return None
    return RecurrenceInstance(
        journal_id=linked.journal_id,
        start=linked.event_date_range_start,
        cancelled=linked.link_sync_status
        == ExternalEventLinkSyncStatus.CANCELLED.value,
    )


class CancelledRecurrenceTidier:
    """Deletes the continuations of a recurrence's cancelled runs."""

    def __init__(
        self,
        connection: AsyncConnection,
        link_repo: SqlJournalEventLinkRepository,
        journal_service: JournalService,
    ) -> None:
        """Initialize over the processor's connection, links and service."""
        self.connection = connection
        self.link_repo = link_repo
        self.journal_service = journal_service

    async def tidy(
        self,
        *,
        calendar_id: UUID,
        recurring_event_id: str,
        source: Provenance,
        changed_by: str,
        cancelled_journal_id: int | None = None,
    ) -> TidyOutcome:
        """Apply the keep-next rule to one recurrence on one calendar.

        Given ``cancelled_journal_id``, only that occurrence and its successor
        are considered - the only two one cancellation can change. Without it
        (a whole series cancelled, or a backfill), every continuation is.
        Call it after the cancellations have been marked on the links.
        """
        linked = await self.link_repo.find_journals_for_series(
            calendar_id=calendar_id, recurring_event_id=recurring_event_id
        )
        await self.link_repo.backfill_recurring_event_id(
            calendar_id,
            recurring_event_id,
            [row.journal_id for row in linked if row.recurring_event_id is None],
        )

        instances = [i for i in map(_as_instance, linked) if i is not None]
        now = datetime.now(UTC)
        verdicts = plan_cancelled_recurrence(instances, now)
        candidates = (
            affected_by_cancel(instances, cancelled_journal_id, now)
            if cancelled_journal_id is not None
            else tuple(verdicts)
        )

        by_id = {row.journal_id: row for row in linked}
        deleted: set[int] = set()
        errors = 0
        for journal_id in candidates:
            if verdicts.get(journal_id) is not CancelledInstanceVerdict.DELETE:
                continue
            try:
                if await self._delete_unless_protected(
                    by_id[journal_id], source=source, changed_by=changed_by
                ):
                    deleted.add(journal_id)
            except Exception:
                errors += 1
                logger.exception(
                    "Failed to delete a cancelled recurrence continuation",
                    journal_id=journal_id,
                    recurring_event_id=recurring_event_id,
                )
        return TidyOutcome(deleted=frozenset(deleted), errors=errors)

    async def _is_protected(self, linked: SeriesLinkedJournal) -> bool:
        if await self.link_repo.has_other_live_links(
            linked.journal_id, linked.calendar_id
        ):
            return True
        facts = await self.link_repo.get_deletion_protection_facts(linked.journal_id)
        if facts.is_protected:
            return True
        return await self.link_repo.has_user_history(linked.journal_id)

    async def _delete_unless_protected(
        self, linked: SeriesLinkedJournal, *, source: Provenance, changed_by: str
    ) -> bool:
        """Delete one continuation; ``False`` when it is kept instead.

        The links go first so the JournalDeleted event carries no external
        identifiers: the upstream occurrence is already cancelled, and an
        outbound deletion would only fail. A task anchored to the journal
        refuses the deletion, which is a keep and not a failure; the
        SAVEPOINT takes back the links the attempt removed.
        """
        if await self._is_protected(linked):
            return False
        try:
            async with savepoint(self.connection):
                await self.link_repo.delete_links_for_journal(linked.journal_id)
                await self.journal_service.delete_journal(
                    linked.journal_id,
                    self.connection,
                    changed_by=changed_by,
                    source=source,
                )
        except JournalHasAnchoredTasksError:
            logger.info(
                "Cancelled continuation kept: tasks are anchored to it",
                journal_id=linked.journal_id,
            )
            return False
        logger.info(
            "Deleted a cancelled recurrence continuation",
            journal_id=linked.journal_id,
            external_event_id=linked.external_event_id,
        )
        return True
