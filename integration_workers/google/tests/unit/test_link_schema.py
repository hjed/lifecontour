"""Unit tests for the gate on the calendar link's synced-base column (#1899)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

import link_schema
from link_schema import link_reference_data_ready

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _session(*, column_exists: bool) -> AsyncMock:
    result = MagicMock()
    result.first.return_value = (1,) if column_exists else None
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.fixture
def unmigrated() -> Iterator[None]:
    """Forget the answer the suite's conftest fixes, as a fresh worker would."""
    link_schema.READINESS.ready = False
    yield
    link_schema.READINESS.ready = True


@pytest.mark.usefixtures("unmigrated")
class TestLinkReferenceDataReady:
    async def test_is_false_before_the_migration_has_run(self) -> None:
        assert await link_reference_data_ready(_session(column_exists=False)) is False

    async def test_asks_again_until_it_has(self) -> None:
        session = _session(column_exists=False)
        await link_reference_data_ready(session)
        session.execute.return_value.first.return_value = (1,)

        assert await link_reference_data_ready(session) is True

    async def test_remembers_once_it_has(self) -> None:
        session = _session(column_exists=True)
        await link_reference_data_ready(session)

        assert await link_reference_data_ready(session) is True
        session.execute.assert_awaited_once()
