"""Contact field-level history *read* service.

ITER12-003 Phase 2 removed the synchronous ``record_*`` write methods: contact
history is now produced solely by the event-driven ``HistoryProjectionConsumer``
from contact domain events. This service is read-only — it backs the REST
``GET /api/contacts/{id}/history`` endpoint and the MCP ``get_contact_history``
tool. The summary generator reads the history repository directly, for a contact
it has already resolved to its owner.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.models.repositories import (
    ContactFieldHistoryEntry,
    ContactFieldHistoryRepository,
    ContactRepository,
)

_TASK_ENTITY_TYPE = "task"


class ContactHistoryService:
    """Read-only service for contact field-level history.

    Every read proves the contact is the reader's first, so another user's
    contact has no history to read through it — it is not found, exactly as a
    missing one is — on REST and MCP alike.
    """

    def __init__(
        self,
        history_repo: ContactFieldHistoryRepository,
        contact_repo: ContactRepository,
    ):
        self.history_repo = history_repo
        self.contact_repo = contact_repo

    async def _require_readable(self, contact_id: int, reader_user_id: str) -> None:
        if not await self.contact_repo.contact_exists(
            contact_id, user_id=reader_user_id
        ):
            raise ContactNotFoundError(contact_id)

    async def get_contact_history(
        self,
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        _transaction: AsyncConnection | None = None,
        *,
        reader_user_id: str,
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination.

        Task rows on this feed are **named** before they are returned. A task
        linked to this person is recorded on the *task* (ITER18-003 Phase 9), so
        the row that reaches a contact's page carries the reader's own id in
        both of its values and nothing that identifies the commitment. Without
        the name the entry reads "Linked to a task" and points at nothing — and
        a task has no route of its own to link to instead.

        One extra query, and only when the page actually holds task rows.

        ``reader_user_id`` must own the contact, and it reaches both the
        aggregate read and the naming query: the task rows are scoped to the
        reader too, so a contact's feed never names another user's commitment.

        Raises:
            ContactNotFoundError: The contact is missing or another user's.
        """
        await self._require_readable(contact_id, reader_user_id)
        entries = await self.history_repo.get_contact_history(
            contact_id, limit, offset, reader_user_id=reader_user_id
        )
        await self._name_the_tasks(entries, reader_user_id=reader_user_id)
        return entries

    async def _name_the_tasks(
        self,
        entries: list[ContactFieldHistoryEntry],
        *,
        reader_user_id: str,
    ) -> None:
        """Stamp ``entity_label`` on the task rows of one page, in place."""
        task_ids = {e.entity_id for e in entries if e.entity_type == _TASK_ENTITY_TYPE}
        if not task_ids:
            return

        labels = await self.history_repo.get_task_labels(
            sorted(task_ids), reader_user_id=reader_user_id
        )
        for entry in entries:
            if entry.entity_type == _TASK_ENTITY_TYPE:
                entry.entity_label = labels.get(entry.entity_id)

    async def get_contact_history_count(
        self,
        contact_id: int,
        _transaction: AsyncConnection | None = None,
        *,
        reader_user_id: str,
    ) -> int:
        """Get total count of history entries for a specific contact.

        Must be given the same reader as the listing: a count computed over a
        wider set would advertise a "Load More" that returns nothing.

        Raises:
            ContactNotFoundError: The contact is missing or another user's.
        """
        await self._require_readable(contact_id, reader_user_id)
        return await self.history_repo.get_contact_history_count(
            contact_id, reader_user_id=reader_user_id
        )
