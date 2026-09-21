"""Which contact domain events integration workers push back to their service.

The contacts domain publishes its events (``ContactCreated``, ``TagAssigned``,
``ContactMethodAdded`` …) to the transactional outbox, which the relay forwards
to the ``pms:domain-events`` Redis stream. Integration workers subscribe to that
stream and push the changed contact out to the remote service.

Before LOCAL-177 each worker listed the event types it consumed by hand, and the
Google worker's list had fallen behind the domain: only the four aggregate-level
events were routed, so adding a tag, adding or removing an email address, and
every important-date edit were read off the stream, acknowledged and discarded.
The change never reached Google, and the next inbound sync overwrote it.

This module is the single source of truth for that classification. Workers derive
their contact routes from :data:`CONTACT_PUSH_EVENT_TYPES`, and a backend guard
test fails whenever an event declared in ``app.core.contacts.models.events`` is
missing from both tuples below — so a newly added contact event cannot silently
miss outbound sync again.

Note this covers the *contact aggregate*. ``TagUpdated``/``TagDeleted`` are
tag-entity events with their own worker handler (they rename or delete the remote
group rather than pushing a contact) and are listed as exclusions here.
"""

from typing import Final

CONTACT_PUSH_EVENT_TYPES: Final[tuple[str, ...]] = (
    # Aggregate-level lifecycle.
    "ContactCreated",
    "ContactUpdated",
    "ContactDeleted",
    "ContactMerged",
    # Tag membership — maps to contact-group membership on the remote service.
    "TagAssigned",
    "TagRemoved",
    # Contact methods — maps to email addresses and phone numbers.
    "ContactMethodAdded",
    "ContactMethodDeleted",
    # Postal addresses.
    "ContactAddressAdded",
    "ContactAddressDeleted",
    # Notes — maps to the remote biography/notes field.
    "ContactNoteAdded",
    # Important dates — maps to birthdays and custom events.
    "ImportantDateAdded",
    "ImportantDateUpdated",
    "ImportantDateDeleted",
)
"""Contact events that must trigger an outbound push of the whole contact.

Handlers re-read the contact from the database and push its full current state,
so the event only needs to identify *which* contact changed, not what changed.
That keeps the push idempotent when several of these arrive for one user action.
"""

CONTACT_PUSH_EVENTS_WITHOUT_CONTACT_ID: Final[tuple[str, ...]] = ("ContactMerged",)
"""Pushed events that do not carry ``event_data["contact_id"]``.

``ContactMerged`` reconciles a survivor/source pair via ``external_collisions``
rather than naming a single contact, so worker handlers branch on it before the
``contact_id`` lookup. Every other pushed event must carry ``contact_id`` or the
handler cannot find the contact to push.
"""

CONTACT_EVENTS_NOT_PUSHED: Final[tuple[tuple[str, str], ...]] = (
    (
        "TagUpdated",
        "Tag-entity event, not a contact change: workers rename the remote "
        "contact group via their own tag handler.",
    ),
    (
        "TagDeleted",
        "Tag-entity event, not a contact change: workers delete the remote "
        "contact group via their own tag handler.",
    ),
    (
        "ContactSummaryRefreshRequested",
        "Internal trigger asking the summary generator to run; carries no "
        "contact data and no remote service holds it.",
    ),
    (
        "ContactSummaryRefreshDue",
        "Internal scheduling trigger for stale summaries; carries no contact "
        "data and no remote service holds it.",
    ),
    (
        "ContactSummaryUpdated",
        "AI-generated relationship summary; local-only by design and has no "
        "field on any integrated service.",
    ),
    (
        "ContactRelationshipCreated",
        "Relationship-aggregate event keyed by relationship, not contact; "
        "pushing relations is not implemented for any integration.",
    ),
    (
        "ContactRelationshipUpdated",
        "Relationship-aggregate event keyed by relationship, not contact; "
        "pushing relations is not implemented for any integration.",
    ),
    (
        "ContactRelationshipDeleted",
        "Relationship-aggregate event keyed by relationship, not contact; "
        "pushing relations is not implemented for any integration.",
    ),
)
"""Contact events deliberately excluded from outbound push, each with a reason.

Pair a new exclusion with its reason: the guard test only checks that every
declared event is classified, so the reason is what stops the next reader having
to work out whether the omission was a decision or an oversight.
"""

__all__ = [
    "CONTACT_EVENTS_NOT_PUSHED",
    "CONTACT_PUSH_EVENTS_WITHOUT_CONTACT_ID",
    "CONTACT_PUSH_EVENT_TYPES",
]
