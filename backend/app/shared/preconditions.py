"""Optimistic-concurrency preconditions for write operations.

One implementation shared by the domains that support conditional writes, so
REST's ``If-Match`` and MCP's ``expected_version`` cannot drift apart in what
they accept or how they refuse.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from core_shared.etag import etag_matches, resource_etag
from core_shared.exceptions import PreconditionFailedError


async def guard_aggregate_write(
    *,
    resource_type: str,
    resource_id: int,
    expected_etags: Sequence[str] | None,
    lock_and_get_updated_at: Callable[[], Awaitable[datetime | None]],
    not_found: Callable[[int], Exception],
) -> datetime:
    """Take an aggregate's row lock for a write, and refuse a stale one.

    Every write to an aggregate - the root row or any child row it renders -
    starts here, inside its unit of work and before it reads or writes
    anything. The lock is taken **whether or not** the caller stated a
    precondition:

    - with one, it is what makes the comparison a guarantee under READ
      COMMITTED rather than a racy read;
    - without one, it is what stops a read-modify-write from overwriting a
      change committed between its read and its write;
    - either way, it fixes the lock order: parent first, then children, so
      writers queue instead of deadlocking.

    Args:
        resource_type: JSON:API resource type, e.g. ``"contacts"``.
        resource_id: The aggregate about to be written.
        expected_etags: The caller's precondition, from
            :func:`core_shared.etag.parse_if_match` or a single MCP
            ``expected_version`` wrapped in a list. ``None`` writes
            unconditionally.
        lock_and_get_updated_at: The repository's row-locking read, scoped to
            the acting user. Its lock mode is the aggregate's to choose.
        not_found: Builds the domain's not-found error for a row that is gone
            (or is somebody else's).

    Returns:
        The aggregate's version as locked: what a write that turns out to
        change nothing reports as the version it leaves behind.

    Raises:
        Exception: ``not_found(resource_id)`` when there is no row to write,
            whatever the precondition - a refusal never invents a version.
        PreconditionFailedError: If the row's version is not among the
            expected ones.
    """
    updated_at = await lock_and_get_updated_at()
    if updated_at is None:
        raise not_found(resource_id)

    current_etag = resource_etag(resource_type, resource_id, updated_at)
    if not etag_matches(current_etag, expected_etags):
        raise PreconditionFailedError(resource_type, resource_id, current_etag)
    return updated_at
