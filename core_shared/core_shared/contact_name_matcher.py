"""Contact name matching utility.

Provides shared name-matching logic for integrations that need to link
external entities (Immich People, Strava athletes) to local contacts.

Supports:
- Exact match (case-insensitive)
- Middle initial variants (e.g. "John A Smith" ↔ "John Smith")
- Abbreviated last name (e.g. "John S" matches "John Smith")

This module lives in ``core_shared`` so it can be reused across
integration workers (Immich, Strava, etc.) without code duplication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core_shared.models.contacts.entities import Contact


@dataclass(frozen=True)
class ParsedName:
    """Result of parsing a full name string into components.

    Attributes:
        first_name: Everything before the last space token.
        last_name: The last space-separated token, or ``None`` for a
            single-token name.
    """

    first_name: str
    last_name: str | None


class ContactNameMatcher:
    """Utility for matching external name strings to local contacts.

    All methods are static and side-effect-free.
    """

    # Regex to collapse multiple whitespace characters into one
    _WHITESPACE_RE = re.compile(r"\s+")

    @staticmethod
    def parse_name(full_name: str) -> tuple[str, str | None]:
        """Split a full name string into ``(first_name, last_name)``.

        Splitting is performed on the *last* space, so multi-word first
        names are preserved::

            "John Michael Smith" → ("John Michael", "Smith")
            "Madonna"            → ("Madonna", None)

        Args:
            full_name: The name string to parse.

        Returns:
            A ``(first_name, last_name)`` tuple.  ``last_name`` is
            ``None`` when the input contains a single token.
        """
        normalised = ContactNameMatcher._WHITESPACE_RE.sub(" ", full_name.strip())
        if not normalised:
            return ("", None)

        parts = normalised.rsplit(" ", maxsplit=1)
        if len(parts) == 1:
            return (parts[0], None)
        return (parts[0], parts[1])

    @staticmethod
    def find_matches(
        name: str,
        contacts: list[Contact],
    ) -> list[Contact]:
        """Find contacts whose name matches *name*.

        Matching strategy (applied in order):

        1. **Exact match** – ``"{first_name} {last_name}"`` equals
           ``name`` (case-insensitive).
        2. **Middle initial variant** – Matches with or without middle
           initials (e.g. "John A Smith" ↔ "John Smith", but "John B
           Smith" does **not** match "John Andrew Smith").
        3. **Abbreviated last name** – When the incoming name uses only
           the first character of the last name (e.g. "John S" matches
           "John Smith").

        Args:
            name: The external name string to match.
            contacts: Local contacts to search through.

        Returns:
            A deduplicated list of matching contacts.
        """
        if not name or not name.strip():
            return []

        parsed_first, parsed_last = ContactNameMatcher.parse_name(name)
        if not parsed_first:
            return []

        matched: dict[int | None, Contact] = {}

        for contact in contacts:
            if ContactNameMatcher._is_match(parsed_first, parsed_last, contact):
                matched[contact.id] = contact

        return list(matched.values())

    # -- Private helpers -------------------------------------------------

    @staticmethod
    def _is_match(
        parsed_first: str,
        parsed_last: str | None,
        contact: Contact,
    ) -> bool:
        """Determine whether a parsed name matches a contact."""
        c_first = (contact.first_name or "").strip().lower()
        c_last = (
            (contact.last_name or "").strip().lower() if contact.last_name else None
        )
        c_middle = (
            (contact.middle_name or "").strip().lower() if contact.middle_name else None
        )

        p_first_lower = parsed_first.lower()
        p_last_lower = parsed_last.lower() if parsed_last else None

        # --- Single-token name (e.g. "Madonna") -----------------------
        if p_last_lower is None:
            # Only match contacts with no last name
            return c_first == p_first_lower and not c_last

        # --- Exact match (ignoring case) ------------------------------
        if c_first == p_first_lower and c_last == p_last_lower:
            return True

        # --- Middle initial variants -----------------------------------
        # Split parsed first name to detect a middle initial
        # e.g. "John A" → first_parts=["john", "a"]
        first_parts = p_first_lower.split()
        if len(first_parts) >= 2:
            # Parsed name has a middle part — check if it's consistent
            base_first = first_parts[0]
            middle_token = " ".join(first_parts[1:])

            if base_first == c_first and p_last_lower == c_last:
                # Check if the middle token is compatible with the
                # contact's middle name (either initial or full name)
                if c_middle:
                    # Contact has a middle name — initial must match
                    if c_middle.startswith(middle_token) or middle_token.startswith(
                        c_middle
                    ):
                        return True
                else:
                    # Contact has no middle name — skip middle initial,
                    # the first+last already matches so this is valid
                    # e.g. "John A Smith" matches "John Smith"
                    return True

        # The contact has a middle name but the parsed name doesn't
        if c_middle and c_last:
            # e.g. Contact "John Andrew Smith" matches "John Smith"
            if c_first == p_first_lower and c_last == p_last_lower:
                # Already handled above in exact match
                return True

        # --- Abbreviated last name -------------------------------------
        # e.g. "John S" matches "John Smith" (single-char last name
        # that matches first char of contact's last name)
        if (
            p_last_lower
            and len(p_last_lower) == 1
            and c_last
            and c_last.startswith(p_last_lower)
            and c_first == p_first_lower
        ):
            return True

        return False
