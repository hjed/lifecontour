"""MCP tools for what integration imports left out of contacts (#1820).

Today: a Google address whose AU/US/CA region names no state, province or
territory. The contact imported without it, and the address stays in Google;
fixing it there imports it on the next sync. The ``@transactional`` service
owns every commit; no tool opens a transaction.
"""

from datetime import datetime
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactImportIssueNotFoundError
from app.core.contacts.services.contact_import_issue_service import (
    ContactImportIssueService,
)
from app.mcp.shared.annotations import IDEMPOTENT_WRITE, READ_ONLY
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_contact_import_issue_service,
    get_current_user_id,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPErrors


class ContactImportIssueMCPEntry(BaseModel):
    id: int
    contact_id: int
    contact_name: str
    integration_source: str
    reason: str
    address: dict[str, Any]
    created_at: datetime


class ContactImportIssuesMCPResponse(BaseModel):
    issues: list[ContactImportIssueMCPEntry]
    total_count: int
    summary: str


class DismissedContactImportIssueMCPResponse(BaseModel):
    issue_id: int
    dismissed: bool
    summary: str


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_contact_import_issues", "contact")
async def list_contact_import_issues(
    contact_id: Annotated[
        int | None, Field(description="Only this contact's issues; all when omitted")
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    service: ContactImportIssueService = mcp_depends(get_contact_import_issue_service),
) -> ContactImportIssuesMCPResponse:
    """
    List what integration imports left out of the user's contacts, to review.

    Each issue is an address an import skipped (reason ``unrecognised_region``:
    its AU/US/CA region names no state, province or territory), with the
    contact it belongs to. Fixing the address at the source imports it on the
    next sync and clears the issue; ``dismiss_contact_import_issue`` hides it.
    """
    issues = await service.list_pending(user_id, contact_id=contact_id)
    return ContactImportIssuesMCPResponse(
        issues=[
            ContactImportIssueMCPEntry(
                id=issue.id,
                contact_id=issue.contact_id,
                contact_name=issue.contact_name,
                integration_source=issue.integration_source,
                reason=issue.reason,
                address=issue.payload,
                created_at=issue.created_at,
            )
            for issue in issues
        ],
        total_count=len(issues),
        summary=f"{len(issues)} import issue(s) to review.",
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("dismiss_contact_import_issue", "contact")
async def dismiss_contact_import_issue(
    issue_id: Annotated[int, Field(description="The issue to dismiss")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    service: ContactImportIssueService = mcp_depends(get_contact_import_issue_service),
) -> DismissedContactImportIssueMCPResponse:
    """
    Dismiss an import issue. It stays dismissed while the import still skips
    the same address; a changed address is reported afresh.
    """
    try:
        await service.dismiss(user_id, issue_id, transaction=db_connection)
    except ContactImportIssueNotFoundError as e:
        raise MCPErrors.not_found("Import issue", issue_id) from e
    return DismissedContactImportIssueMCPResponse(
        issue_id=issue_id,
        dismissed=True,
        summary=f"Import issue {issue_id} dismissed.",
    )


def register_contact_import_issue_tools(mcp: FastMCP[None]) -> None:
    """Register the import-issue tools."""
    mcp.add_tool(list_contact_import_issues)
    mcp.add_tool(dismiss_contact_import_issue)
