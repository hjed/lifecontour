"""What integration imports left out of contacts, for the user to review.

Today: a Google address whose AU/US/CA region names no state, province or
territory (#1820). The contact imported without it; fixing it in Google
imports it on the next sync, which also clears the issue.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.contact_import_issue_schemas import (
    ContactImportIssueListResponse,
    to_resource,
)
from app.core.contacts.services.contact_import_issue_service import (
    ContactImportIssueService,
)
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/integrations/import-issues", tags=["integrations-contacts"])


@router.get("")
@inject
async def list_contact_import_issues(
    service: FromDishka[ContactImportIssueService],
    user: FromDishka[SessionUser],
    contact_id: int | None = None,
) -> ContactImportIssueListResponse:
    """The user's pending import issues, optionally for one contact."""
    issues = await service.list_pending(user.id, contact_id=contact_id)
    return ContactImportIssueListResponse(data=[to_resource(i) for i in issues])


@router.post("/{issue_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def dismiss_contact_import_issue(
    issue_id: int,
    service: FromDishka[ContactImportIssueService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> Response:
    """Dismiss an issue. It stays dismissed while the import still skips it."""
    await service.dismiss(user.id, issue_id, transaction=connection)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
