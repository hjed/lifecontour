"""Merge a contact push into the Google person as it stands.

A push names fields in ``updatePersonFields`` and Google replaces each named
field wholesale, while the payload is built from the local contact alone. The
merge folds back the values of those fields the local model does not own, so a
push changes only what the local contact can represent (#1732).

Which entry the local model owns mirrors inbound sync (``transformer.py``): the
primary name, else the first; the first current organization, else the first;
the ``anniversary`` events. Values held by a person's profile rather than the
contact itself are never copied into the contact.
"""

from typing import Any

# Name parts the local model cannot represent, kept from Google's name; the
# local contact owns given, family and middle name. unstructuredName is left out: Google formats the display name from the
# structured parts, and a stale free-form name could contradict a local rename.
_PRESERVED_NAME_KEYS = frozenset(
    {
        "honorificPrefix",
        "honorificSuffix",
        "phoneticFullName",
        "phoneticGivenName",
        "phoneticMiddleName",
        "phoneticFamilyName",
        "phoneticHonorificPrefix",
        "phoneticHonorificSuffix",
    }
)

# Organization parts the local contact owns (company and job title).
_OWNED_ORGANIZATION_KEYS = frozenset({"name", "title"})

# Event types the local contact owns, matching inbound sync's event type map.
_OWNED_EVENT_TYPES = frozenset({"anniversary"})

# Output-only parts of a field entry, never sent back to Google.
_OUTPUT_ONLY_KEYS = frozenset({"metadata", "formattedType"})

# Sources whose values belong to a profile, not to the contact being pushed.
_PROFILE_SOURCE_TYPES = frozenset({"PROFILE", "DOMAIN_PROFILE"})


def merge_with_current_person(
    payload: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Return ``payload`` with the values it does not own kept from ``current``.

    Only fields the payload already carries are merged, so the update mask is
    unchanged. ``payload`` itself is left untouched.
    """
    merged = dict(payload)
    if "names" in payload:
        merged["names"] = _merge_names(payload["names"], current.get("names") or [])
    if "events" in payload:
        merged["events"] = _merge_events(payload["events"], current.get("events") or [])
    if "organizations" in payload:
        merged["organizations"] = _merge_organizations(
            payload["organizations"], current.get("organizations") or []
        )
    return merged


def _is_contact_entry(entry: dict[str, Any]) -> bool:
    """Whether an entry belongs to the contact rather than a linked profile."""
    source_type = (entry.get("metadata") or {}).get("source", {}).get("type")
    return source_type not in _PROFILE_SOURCE_TYPES


def _writable(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry without its output-only parts."""
    return {key: value for key, value in entry.items() if key not in _OUTPUT_ONLY_KEYS}


def _merge_names(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Add the current name's honorifics and phonetic parts to the pushed name."""
    if not pushed or not current:
        return pushed
    owned = next(
        (name for name in current if (name.get("metadata") or {}).get("primary")),
        current[0],
    )
    if not _is_contact_entry(owned):
        return pushed
    preserved = {
        key: value for key, value in owned.items() if key in _PRESERVED_NAME_KEYS
    }
    return [{**pushed[0], **preserved}, *pushed[1:]]


def _merge_events(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append the current events of every type the local contact does not own."""
    kept = [
        _writable(event)
        for event in current
        if _is_contact_entry(event)
        and str(event.get("type") or "").lower() not in _OWNED_EVENT_TYPES
    ]
    return [*pushed, *kept]


def _merge_organizations(
    pushed: list[dict[str, Any]], current: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Write the pushed organization over the owned one, keeping the others."""
    if not pushed or not current:
        return pushed
    owned_index = next(
        (index for index, org in enumerate(current) if org.get("current") is True),
        0,
    )
    owned = current[owned_index]
    merged: list[dict[str, Any]] = []
    if not _is_contact_entry(owned):
        merged.append(pushed[0])
    for index, org in enumerate(current):
        if not _is_contact_entry(org):
            continue
        if index == owned_index:
            kept = {
                key: value
                for key, value in _writable(org).items()
                if key not in _OWNED_ORGANIZATION_KEYS
            }
            merged.append({**kept, **pushed[0]})
        else:
            merged.append(_writable(org))
    return [*merged, *pushed[1:]]
