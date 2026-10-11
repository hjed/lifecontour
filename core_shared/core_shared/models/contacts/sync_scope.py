"""What an inbound contact sync may change: the fields its source owns.

An integration's sync event carries the whole contact, but a source only knows
some of it - Google is never asked for the avatar Immich set, and neither
models a first-met date. A field the source does not own must keep its stored
value rather than be overwritten with the payload's empty default.

The scope is an allow-list declared by the producing worker, beside the fields
it requests from its provider, so a field added to contacts later is safe from
every sync until a source claims it.
"""

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from core_shared.models.contacts.entities import Contact
from core_shared.models.contacts.important_date_types import ImportantDateType


class ContactSyncField(StrEnum):
    """A contact field an inbound sync may own; values are ``Contact`` attributes.

    Important dates are owned per date type instead, see
    :attr:`ContactSyncScope.important_date_types`.
    """

    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    MIDDLE_NAME = "middle_name"
    NICK_NAME = "nick_name"
    COMPANY = "company"
    JOB_TITLE = "job_title"
    PHOTO_URL = "photo_url"
    IS_FAVOURITE = "is_favourite"
    METHODS = "methods"
    ADDRESSES = "addresses"
    NOTES = "notes"
    TAGS = "tags"


# Written whole by the contact save, so an unowned one takes the stored value.
_SCALAR_FIELDS = frozenset(
    {
        ContactSyncField.FIRST_NAME,
        ContactSyncField.LAST_NAME,
        ContactSyncField.MIDDLE_NAME,
        ContactSyncField.NICK_NAME,
        ContactSyncField.COMPANY,
        ContactSyncField.JOB_TITLE,
        ContactSyncField.PHOTO_URL,
        ContactSyncField.IS_FAVOURITE,
    }
)
# Reconciled by the contact save only when not None, so an unowned one is None.
_LIST_FIELDS = frozenset(ContactSyncField) - _SCALAR_FIELDS


class ContactSyncScope(BaseModel):
    """The contact fields and important-date types an inbound sync owns."""

    model_config = ConfigDict(frozen=True)

    fields: frozenset[ContactSyncField] = Field(
        description="Contact fields the source owns"
    )
    important_date_types: frozenset[ImportantDateType] = Field(
        default=frozenset(),
        description="Important-date types the source owns",
    )

    @field_serializer("fields", "important_date_types")
    def _serialize_sorted(
        self, values: Iterable[ContactSyncField | ImportantDateType]
    ) -> list[str]:
        # Sorted values keep the stored event JSON-safe and deterministic.
        return sorted(value.value for value in values)


def apply_sync_scope(
    incoming: Contact, stored: Contact, scope: ContactSyncScope | None
) -> None:
    """Limit ``incoming`` to what ``scope`` owns, in place, before it is saved.

    - an unowned scalar takes ``stored``'s value;
    - an unowned list becomes None, which the save leaves untouched;
    - important dates of owned types are taken from ``incoming`` and the stored
      dates of every other type are kept (by id, so they are not re-created).
      None still means "leave the dates alone", as for any list.

    ``scope`` None is an event queued before scopes existed: unchanged.
    """
    if scope is None:
        return

    for field in _SCALAR_FIELDS - scope.fields:
        setattr(incoming, field.value, getattr(stored, field.value))
    for field in _LIST_FIELDS - scope.fields:
        setattr(incoming, field.value, None)

    owned_types = scope.important_date_types
    if not owned_types or incoming.important_dates is None:
        incoming.important_dates = None
        return
    incoming.important_dates = [
        *(d for d in incoming.important_dates if d.date_type in owned_types),
        *(d for d in stored.important_dates or [] if d.date_type not in owned_types),
    ]
