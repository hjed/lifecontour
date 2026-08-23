"""Optimistic-concurrency preconditions for write operations.

One implementation shared by the domains that support conditional writes, so
REST's ``If-Match`` and MCP's ``expected_version`` cannot drift apart in what
they accept or how they refuse.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from core_shared.etag import etag_matches, resource_etag
from core_shared.exceptions import PreconditionFailedError


async def enforce_etag_precondition(
    *,
    resource_type: str,
    resource_id: int,
    expected_etags: Sequence[str] | None,
    lock_and_get_updated_at: Callable[[int], Awaitable[datetime | None]],
) -> None:
    """Refuse a write whose caller expected a version the row no longer has.

    Call this from inside the write's unit of work and **before** anything is
    written — including any find-or-create of related rows — so a refusal
    leaves nothing behind.

    Args:
        resource_type: JSON:API resource type, e.g. ``"journals"``.
        resource_id: The resource about to be written.
        expected_etags: The caller's precondition, from
            :func:`core_shared.etag.parse_if_match` or a single MCP
            ``expected_version`` wrapped in a list. ``None`` means the caller
            stated no precondition and the write proceeds unconditionally.
        lock_and_get_updated_at: The repository's row-locking read. Taking the
            lock here is what makes the check a real guarantee rather than a
            racy comparison.

    Raises:
        PreconditionFailedError: If the row's current version is not among the
            expected ones.
    """
    if expected_etags is None:
        return

    current_etag = resource_etag(
        resource_type, resource_id, await lock_and_get_updated_at(resource_id)
    )
    if not etag_matches(current_etag, expected_etags):
        raise PreconditionFailedError(resource_type, resource_id, current_etag)
