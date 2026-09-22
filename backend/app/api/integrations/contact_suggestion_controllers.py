"""REST endpoints for contact suggestions.

Participant emails that integrations reported on enough of a user's journals,
but that match no contact, are suggested as contacts on the Integrations page.
These endpoints list them, accept one (as a new contact or into an existing
one) and manage the user's ignore list. The service owns every commit.
"""

from typing import assert_never

from core_shared.models.history import Provenance
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.contact_suggestion_schemas import (
    AcceptContactSuggestionRequest,
    AcceptTargetSchema,
    ContactSuggestionAcceptanceAttributes,
    ContactSuggestionAcceptanceResource,
    ContactSuggestionAcceptanceResponse,
    ContactSuggestionAttributes,
    ContactSuggestionListResponse,
    ContactSuggestionResource,
    ExistingContactTargetSchema,
    IgnoreContactSuggestionRequest,
    IgnoredContactSuggestionAttributes,
    IgnoredContactSuggestionListResponse,
    IgnoredContactSuggestionResource,
    IgnoredContactSuggestionResponse,
    NewContactTargetSchema,
)
from app.core.integrations.services.contact_suggestion_service import (
    AcceptTarget,
    ContactSuggestionService,
    ExistingContactTarget,
    NewContactTarget,
)
from app.infrastructure.auth.models import SessionUser

router = APIRouter(
    prefix="/integrations/contact-suggestions", tags=["integrations-contacts"]
)


def _to_target(schema: AcceptTargetSchema) -> AcceptTarget:
    match schema:
        case NewContactTargetSchema(first_name=first_name, last_name=last_name):
            return NewContactTarget(first_name=first_name, last_name=last_name)
        case ExistingContactTargetSchema(contact_id=contact_id):
            return ExistingContactTarget(contact_id=contact_id)
        case _:
            assert_never(schema)


@router.get("")
@inject
async def list_contact_suggestions(
    service: FromDishka[ContactSuggestionService],
    user: FromDishka[SessionUser],
) -> ContactSuggestionListResponse:
    """
    List participant emails seen on at least five of the user's journals that
    match no contact and have not been ignored, most-seen first.
    """
    suggestions = await service.list_suggestions(user.id)
    return ContactSuggestionListResponse(
        data=[
            ContactSuggestionResource(
                id=s.email,
                attributes=ContactSuggestionAttributes(
                    email=s.email,
                    display_name=s.display_name,
                    event_count=s.event_count,
                    last_seen_at=s.last_seen_at,
                ),
            )
            for s in suggestions
        ]
    )


@router.post(
    "/accept",
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "The existing contact was not found"}},
)
@inject
async def accept_contact_suggestion(
    request: AcceptContactSuggestionRequest,
    service: FromDishka[ContactSuggestionService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> ContactSuggestionAcceptanceResponse:
    """
    Make the email a contact's -- a new contact, or added to an existing one --
    and link that contact to every journal the email was seen on.
    """
    attributes = request.data.attributes
    accepted = await service.accept(
        user.id,
        attributes.email,
        _to_target(attributes.target),
        transaction=connection,
        provenance=Provenance.UI,
    )
    contact_id = accepted.contact.id
    assert contact_id is not None  # a saved contact always has one
    return ContactSuggestionAcceptanceResponse(
        data=ContactSuggestionAcceptanceResource(
            id=attributes.email,
            attributes=ContactSuggestionAcceptanceAttributes(
                email=attributes.email,
                contact_id=contact_id,
                linked_journal_count=accepted.linked_journal_count,
            ),
        )
    )


@router.get("/ignored")
@inject
async def list_ignored_contact_suggestions(
    service: FromDishka[ContactSuggestionService],
    user: FromDishka[SessionUser],
) -> IgnoredContactSuggestionListResponse:
    """List the emails the user has asked never to have suggested."""
    ignored = await service.list_ignored(user.id)
    return IgnoredContactSuggestionListResponse(
        data=[
            IgnoredContactSuggestionResource(
                id=i.email,
                attributes=IgnoredContactSuggestionAttributes(
                    email=i.email,
                    provenance=i.provenance.value,
                    created_at=i.created_at,
                ),
            )
            for i in ignored
        ]
    )


@router.post("/ignored", status_code=status.HTTP_201_CREATED)
@inject
async def ignore_contact_suggestion(
    request: IgnoreContactSuggestionRequest,
    service: FromDishka[ContactSuggestionService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> IgnoredContactSuggestionResponse:
    """Never suggest the email again. Ignoring it twice changes nothing."""
    email = request.data.attributes.email
    await service.ignore(
        user.id, email, transaction=connection, provenance=Provenance.UI
    )
    return IgnoredContactSuggestionResponse(
        data=IgnoredContactSuggestionResource(
            id=email,
            attributes=IgnoredContactSuggestionAttributes(
                email=email, provenance=Provenance.UI.value
            ),
        )
    )


# ``:path`` so an address with a ``/`` in its local part still routes here.
@router.delete("/ignored/{email:path}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def unignore_contact_suggestion(
    email: str,
    service: FromDishka[ContactSuggestionService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> Response:
    """Let the email be suggested again. Idempotent."""
    await service.unignore(user.id, email, transaction=connection)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
