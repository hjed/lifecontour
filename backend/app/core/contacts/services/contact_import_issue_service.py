"""Review of what integration imports left out of contacts (#1820)."""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_import_issue_repository import (
    SqlContactImportIssueRepository,
)
from app.core.contacts.models.exceptions import ContactImportIssueNotFoundError
from app.core.contacts.models.import_issues import ContactImportIssue
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
    async def dismiss(
        self, user_id: str, issue_id: int, transaction: AsyncConnection
    ) -> None:
        """Dismiss the issue; one the user does not hold is not found."""
        if not await self.repository.dismiss(user_id, issue_id):
            raise ContactImportIssueNotFoundError(issue_id)
