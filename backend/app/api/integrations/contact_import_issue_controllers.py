"""What integration imports left out of contacts, for the user to review.

Today: a Google address whose AU/US/CA region names no state, province or
territory (#1820). The contact imported without it; fixing it in Google
imports it on the next sync, which also clears the issue.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.contact_import_issue_schemas import (
    ContactImportIssueListResponse,
    CreatedContactImportIssueData,
    CreatedContactImportIssueResponse,
    SkippedAddressCreateRequest,
    to_resource,
)
from app.core.contacts.services.contact_import_issue_service import (
    ContactImportIssueService,
)
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AdminAccess

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


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_contact_import_issue(
    request: SkippedAddressCreateRequest,
    service: FromDishka[ContactImportIssueService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
    settings: FromDishka[Settings],
    _admin: FromDishka[AdminAccess],
) -> CreatedContactImportIssueResponse:
    """Record a skipped address (test-only endpoint).

    Gated behind ``ENABLE_TEST_IMPORT_ISSUES`` for the e2e stack, which has no
    Google import to skip one; a real issue is recorded from the import.
    """
    if not settings.enable_test_import_issues:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    attributes = request.data.attributes
    issue_id = await service.record_skipped_address(
        user.id,
        attributes.contact_id,
        attributes.address.model_dump(),
        transaction=connection,
    )
    return CreatedContactImportIssueResponse(
        data=CreatedContactImportIssueData(id=str(issue_id))
    )


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
