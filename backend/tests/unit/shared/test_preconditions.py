"""Unit tests for the aggregate write guard."""

from datetime import UTC, datetime

import pytest
from core_shared.etag import resource_etag
from core_shared.exceptions import PreconditionFailedError

from app.shared.preconditions import guard_aggregate_write

VERSION = datetime(2026, 10, 18, 9, 30, tzinfo=UTC)
CURRENT_TAG = f"{resource_etag('contacts', 7, VERSION)}"


class MissingError(Exception):
    """Stands in for a domain's not-found error."""


class LockingRead:
    """Records whether the guard took the lock, and answers with a version."""

    def __init__(self, version: datetime | None) -> None:
        self.version = version
        self.calls = 0

    async def __call__(self) -> datetime | None:
        self.calls += 1
        return self.version


async def _guard(read: LockingRead, expected_etags: list[str] | None) -> datetime:
    return await guard_aggregate_write(
        resource_type="contacts",
        resource_id=7,
        expected_etags=expected_etags,
        lock_and_get_updated_at=read,
        not_found=MissingError,
    )


class TestGuardAggregateWrite:
    async def test_locks_even_when_the_caller_states_no_precondition(self) -> None:
        """An unconditional write still races; the lock is what serialises it."""
        read = LockingRead(VERSION)

        assert await _guard(read, None) == VERSION
        assert read.calls == 1

    async def test_returns_the_locked_version_when_the_tag_matches(self) -> None:
        read = LockingRead(VERSION)

        assert await _guard(read, [CURRENT_TAG]) == VERSION

    async def test_refuses_a_stale_tag_naming_the_current_one(self) -> None:
        read = LockingRead(VERSION)

        with pytest.raises(PreconditionFailedError) as refused:
            await _guard(read, ['"stale"'])

        assert refused.value.current_etag == CURRENT_TAG

    async def test_wildcard_needs_only_the_row_to_exist(self) -> None:
        assert await _guard(LockingRead(VERSION), ["*"]) == VERSION

    @pytest.mark.parametrize("expected_etags", [None, ["*"], ['"stale"']])
    async def test_a_missing_row_is_not_found_whatever_the_precondition(
        self, expected_etags: list[str] | None
    ) -> None:
        """Not found wins over 412, so a refusal never invents a version."""
        with pytest.raises(MissingError):
            await _guard(LockingRead(None), expected_etags)
