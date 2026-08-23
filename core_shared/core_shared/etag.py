"""Entity-tag computation and precondition matching for optimistic concurrency.

A resource's tag is derived from its ``updated_at`` timestamp, which every
write already bumps — so no version column, and no migration. The tag is
opaque to clients: they read one, hand it back on the next write, and the
server refuses the write if the row has moved on.

Shared rather than backend-local because both surfaces mint the same token:
REST carries it in ``ETag`` / ``If-Match`` headers, and the MCP tools — which
have no headers — carry it as a ``version`` / ``expected_version`` parameter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

#: Half a SHA-256 is far more than enough to tell two versions of one row
#: apart, and keeps the header short enough to read in a log line.
ETAG_DIGEST_LENGTH = 16

#: ``If-Match: *`` asks only that the resource exist.
WILDCARD = "*"


def resource_etag(
    resource_type: str, resource_id: int | str, updated_at: datetime | None
) -> str | None:
    """Return the quoted strong entity-tag for one version of a resource.

    The type and id are folded in alongside the timestamp because ``now()`` is
    the *transaction* timestamp: rows written together share an ``updated_at``
    to the microsecond, and a tag over the timestamp alone would collide across
    them.

    Args:
        resource_type: JSON:API resource type, e.g. ``"journals"``.
        resource_id: The resource's identifier.
        updated_at: When the row was last written.

    Returns:
        The tag including its surrounding quotes, or ``None`` when
        ``updated_at`` is unknown and there is therefore no version to guard.
    """
    if updated_at is None:
        return None

    digest = hashlib.sha256(
        f"{resource_type}:{resource_id}:{updated_at.isoformat()}".encode()
    ).hexdigest()
    return f'"{digest[:ETAG_DIGEST_LENGTH]}"'


def normalise_etag(value: str) -> str:
    """Reduce an entity-tag to its bare token for comparison.

    Strips surrounding whitespace, an optional weak ``W/`` prefix and the
    quotes. See :func:`etag_matches` for why weakness is discarded rather than
    being treated as a mismatch.
    """
    token = value.strip()
    if token[:2].upper() == "W/":
        token = token[2:].strip()
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    return token


def parse_if_match(header_value: str | None) -> list[str] | None:
    """Split an ``If-Match`` header into the entity-tags it lists.

    Args:
        header_value: The raw header, or ``None`` when the client sent none.

    Returns:
        ``None`` when there is no precondition to check — the write proceeds
        as it always has. Otherwise the listed tags, which may be ``["*"]``.
        An empty or whitespace-only header yields ``[]``, a precondition
        nothing satisfies: the client asked for a guarded write, and answering
        200 to a guarantee that was never checked is worse than refusing.

    Note:
        Tags are split on commas. The grammar technically permits a comma
        inside an entity-tag; every tag this system mints is hex, so none
        contains one.
    """
    if header_value is None:
        return None

    return [tag.strip() for tag in header_value.split(",") if tag.strip()]


def etag_matches(current: str | None, candidates: Sequence[str] | None) -> bool:
    """Whether a parsed precondition permits writing over ``current``.

    Weak tags compare equal to their strong counterparts here, which ``If-Match``
    strictly forbids. Every tag this system mints is strong, so a weak one can
    only be a strong tag that a compressing proxy weakened on the way out; a
    client echoing it back has done nothing wrong and should not be refused.

    Args:
        current: The resource's tag right now, or ``None`` if it has no known
            version.
        candidates: Tags from :func:`parse_if_match`, or ``None`` for no
            precondition.
    """
    if candidates is None:
        return True

    if any(candidate.strip() == WILDCARD for candidate in candidates):
        # The resource exists — the caller's 404 check settled that — and the
        # wildcard asks for nothing more, so an unknown ``current`` is fine.
        return True

    if current is None:
        return False

    normalised_current = normalise_etag(current)
    return any(
        normalise_etag(candidate) == normalised_current for candidate in candidates
    )
