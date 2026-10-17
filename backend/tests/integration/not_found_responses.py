"""Comparing a refusal of another user's contact with a refusal of a missing one.

Another user's contact must be indistinguishable from a contact that does not
exist. The not-found detail names the id the caller sent ("Contact with ID 7
not found"), so two refusals are compared with that id masked: what remains
must be identical. Each error's own ``id`` is unique per response, so it is
left out.
"""

import re
from typing import Any, Final

from httpx import Response

# An id no seeded contact holds.
MISSING_CONTACT_ID: Final = 999_999


def masked_errors(response: Response, contact_id: int) -> list[dict[str, Any]]:
    """The response's JSON:API errors, with ``contact_id`` replaced by ``<id>``.

    The error's own ``id`` (a fresh UUID per response) is dropped.

    Word boundaries keep a short id from rewriting a longer number that happens
    to contain it.
    """
    pattern = re.compile(rf"\b{contact_id}\b")
    errors: list[dict[str, Any]] = response.json()["errors"]
    return [
        {
            key: pattern.sub("<id>", value) if isinstance(value, str) else value
            for key, value in error.items()
            if key != "id"
        }
        for error in errors
    ]
