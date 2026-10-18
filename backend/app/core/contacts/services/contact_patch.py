"""A partial update of a contact, applied to the contact as it stands.

See :mod:`app.shared.patch` for why a caller names its changes instead of
handing over a whole contact built from a read of its own.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from core_shared.models.contacts.entities import (
    Contact,
    ContactNote,
    ImportantDate,
    MethodType,
)

from app.core.contacts.services.contact_subentity_sync import with_primary_method
from app.shared.patch import UNSET, FieldPatch, Unset

#: Builds the contact to save from the contact as stored, read under its row
#: lock. ``None`` means "nothing to write": no save, no event.
type ContactMutation = Callable[[Contact], Awaitable[Contact | None]]


@dataclass(frozen=True, kw_only=True)
class ContactFieldsPatch(FieldPatch):
    """The contact's own fields a caller changes."""

    first_name: str | Unset = UNSET
    last_name: str | None | Unset = UNSET
    middle_name: str | None | Unset = UNSET
    nick_name: str | None | Unset = UNSET
    company: str | None | Unset = UNSET
    job_title: str | None | Unset = UNSET


@dataclass(frozen=True, kw_only=True)
class ContactPatch:
    """Everything a partial update of a contact changes, named rather than listed.

    Child rows are merged into what is stored rather than replaced by a list
    the caller built: setting a primary email keeps the phone beside it, and
    adding a note keeps the notes already there - including any added while
    the caller was deciding.

    Attributes:
        fields: The contact's own fields to change.
        primary_methods: A primary value to set per method type; any other
            method of the type stays, demoted.
        new_notes: Notes to add after the stored ones.
        important_dates: The whole set of important dates, replacing the
            stored set; ``None`` leaves them alone.
        tag_names: The whole set of tags by name, replacing the stored set;
            ``None`` leaves them alone. Resolved by the service, which may
            create a tag.
    """

    fields: ContactFieldsPatch = field(default_factory=ContactFieldsPatch)
    primary_methods: Mapping[MethodType, str] = field(default_factory=dict)
    new_notes: Sequence[str] = ()
    important_dates: Sequence[ImportantDate] | None = None
    tag_names: Sequence[str] | None = None

    def apply_to(self, stored: Contact) -> Contact:
        """The contact to save: ``stored`` with this patch's changes.

        Every child collection the patch does not change is left ``None``,
        which the save reads as "leave as stored". ``stored`` is not modified.
        """
        desired = self.fields.applied_to(
            replace(
                stored,
                methods=None,
                addresses=None,
                notes=None,
                tags=None,
                relationships=None,
                important_dates=None,
                summary=None,
            )
        )
        contact_id = stored.id or 0
        if self.primary_methods:
            methods = list(stored.methods or [])
            for method_type, value in self.primary_methods.items():
                methods = with_primary_method(methods, method_type, value, contact_id)
            desired.methods = methods
        if self.new_notes:
            desired.notes = [
                *(stored.notes or []),
                *(
                    ContactNote(content=content, contact_id=contact_id)
                    for content in self.new_notes
                ),
            ]
        if self.important_dates is not None:
            desired.important_dates = list(self.important_dates)
        return desired
