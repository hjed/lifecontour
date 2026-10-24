"""JSON:API schemas for the contact import-issue endpoints (#1820)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.contacts.models.import_issues import ContactImportIssue


class SkippedAddressSchema(BaseModel):
    street_line_1: str
    street_line_2: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str


class ContactImportIssueAttributes(BaseModel):
    contact_id: int
    contact_name: str
    integration_source: str = Field(
        description="The import that skipped it, e.g. 'google'"
    )
    kind: Literal["skipped_address"]
    reason: str = Field(
        description="Why it was skipped: 'unrecognised_region' - its AU/US/CA "
        "region names no state, province or territory"
    )
    address: SkippedAddressSchema
    created_at: datetime


class ContactImportIssueResource(BaseModel):
    type: Literal["contact-import-issues"] = "contact-import-issues"
    id: str
    attributes: ContactImportIssueAttributes


class ContactImportIssueListResponse(BaseModel):
    data: list[ContactImportIssueResource]


def to_resource(issue: ContactImportIssue) -> ContactImportIssueResource:
    return ContactImportIssueResource(
        id=str(issue.id),
        attributes=ContactImportIssueAttributes(
            contact_id=issue.contact_id,
            contact_name=issue.contact_name,
            integration_source=issue.integration_source,
            kind="skipped_address",
            reason=issue.reason,
            address=SkippedAddressSchema.model_validate(issue.payload),
            created_at=issue.created_at,
        ),
    )
