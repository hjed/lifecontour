"""Review of what integration imports left out of contacts (#1820)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_import_issue_repository import (
    SqlContactImportIssueRepository,
)
from app.core.contacts.models.exceptions import (
    ContactImportIssueNotFoundError,
    ContactNotFoundError,
)
from app.core.contacts.models.import_issues import SKIPPED_ADDRESS, ContactImportIssue
from app.infrastructure.unit_of_work import transactional


class ContactImportIssueService:
    """Lists and dismisses a user's import issues."""

    def __init__(self, repository: SqlContactImportIssueRepository) -> None:
        self.repository = repository

    async def list_pending(
        self, user_id: str, *, contact_id: int | None = None
    ) -> list[ContactImportIssue]:
        """The user's pending issues; another user's contact simply lists none."""
        return await self.repository.list_pending(user_id, contact_id=contact_id)

    @transactional
    async def record_skipped_address(
        self,
        user_id: str,
        contact_id: int,
        address: dict[str, Any],
        transaction: AsyncConnection,
    ) -> int:
        """Record a skipped Google address by hand - the e2e stack's stand-in.

        A real one is recorded by the processor from the import's event.
        """
        issue_id = await self.repository.add(
            user_id=user_id,
            contact_id=contact_id,
            integration_source="google",
            external_id="people/test",
            kind=SKIPPED_ADDRESS,
            reason="unrecognised_region",
            payload=address,
        )
        if issue_id is None:
            raise ContactNotFoundError(contact_id)
        return issue_id

    @transactional
    async def dismiss(
        self, user_id: str, issue_id: int, transaction: AsyncConnection
    ) -> None:
        """Dismiss the issue; one the user does not hold is not found."""
        if not await self.repository.dismiss(user_id, issue_id):
            raise ContactImportIssueNotFoundError(issue_id)
