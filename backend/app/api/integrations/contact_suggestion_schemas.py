"""JSON:API schemas for the contact-suggestion endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from core_shared.models.contacts.exceptions import ContactValidationError
from pydantic import BaseModel, Field, field_validator

from app.core.integrations.services.contact_suggestion_service import canonical_email


def _normalised_email(value: str) -> str:
    try:
        return canonical_email(value)
    except ContactValidationError as error:
        raise ValueError("must be an email address") from error


class ContactSuggestionAttributes(BaseModel):
    email: str
    display_name: str | None = Field(
        description="The name integrations most often reported for the email"
    )
    event_count: int = Field(description="How many journals the email was seen on")
    last_seen_at: datetime = Field(
        description="Start of the most recent journal the email was seen on"
    )


class ContactSuggestionResource(BaseModel):
    type: Literal["contact-suggestions"] = "contact-suggestions"
    id: str = Field(description="The suggested email")
    attributes: ContactSuggestionAttributes


class ContactSuggestionListResponse(BaseModel):
    data: list[ContactSuggestionResource]


class NewContactTargetSchema(BaseModel):
    kind: Literal["new"]
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)

    @field_validator("first_name")
    @classmethod
    def _first_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("last_name")
    @classmethod
    def _blank_last_name_is_none(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()


class ExistingContactTargetSchema(BaseModel):
    kind: Literal["existing"]
    contact_id: int


AcceptTargetSchema = Annotated[
    NewContactTargetSchema | ExistingContactTargetSchema,
    Field(discriminator="kind"),
]


class AcceptContactSuggestionAttributes(BaseModel):
    email: str
    target: AcceptTargetSchema

    _normalise_email = field_validator("email")(_normalised_email)


class AcceptContactSuggestionData(BaseModel):
    type: Literal["contact-suggestion-acceptances"]
    attributes: AcceptContactSuggestionAttributes


class AcceptContactSuggestionRequest(BaseModel):
    data: AcceptContactSuggestionData


class ContactSuggestionAcceptanceAttributes(BaseModel):
    email: str
    contact_id: int
    linked_journal_count: int = Field(
        description="Journals the contact was newly linked to"
    )


class ContactSuggestionAcceptanceResource(BaseModel):
    type: Literal["contact-suggestion-acceptances"] = "contact-suggestion-acceptances"
    id: str = Field(description="The accepted email")
    attributes: ContactSuggestionAcceptanceAttributes


class ContactSuggestionAcceptanceResponse(BaseModel):
    data: ContactSuggestionAcceptanceResource


class IgnoreContactSuggestionAttributes(BaseModel):
    email: str

    _normalise_email = field_validator("email")(_normalised_email)


class IgnoreContactSuggestionData(BaseModel):
    type: Literal["ignored-contact-suggestions"]
    attributes: IgnoreContactSuggestionAttributes


class IgnoreContactSuggestionRequest(BaseModel):
    data: IgnoreContactSuggestionData


class IgnoredContactSuggestionAttributes(BaseModel):
    email: str
    provenance: str
    created_at: datetime | None = None


class IgnoredContactSuggestionResource(BaseModel):
    type: Literal["ignored-contact-suggestions"] = "ignored-contact-suggestions"
    id: str = Field(description="The ignored email")
    attributes: IgnoredContactSuggestionAttributes


class IgnoredContactSuggestionResponse(BaseModel):
    data: IgnoredContactSuggestionResource


class IgnoredContactSuggestionListResponse(BaseModel):
    data: list[IgnoredContactSuggestionResource]
