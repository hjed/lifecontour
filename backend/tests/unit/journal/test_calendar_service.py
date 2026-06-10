"""Unit tests for CalendarService."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import Calendar, CalendarNotFoundError

from app.core.journal.services.calendar_service import (
    CalendarInUseError,
    CalendarPermissionError,
    CalendarService,
)


@pytest.fixture
def mock_calendar_repo():
    """Create a mock calendar repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def calendar_service(mock_calendar_repo):
    """Create a CalendarService instance."""
    return CalendarService(mock_calendar_repo)


def _calendar(**overrides) -> Calendar:
    """Build a valid Calendar with sensible defaults for tests."""
    defaults: dict[str, Any] = {
        "user_id": "user-1",
        "name": "Work",
        "color": "#3B82F6",
    }
    defaults.update(overrides)
    return Calendar(**defaults)


class TestCreateCalendar:
    """Test the create_calendar unit of work."""

    @pytest.mark.asyncio
    async def test_create_calendar_persists_and_returns(
        self, calendar_service, mock_calendar_repo, mock_transaction
    ):
        """create_calendar saves via the repo and returns the saved entity."""
        calendar = _calendar()
        saved = _calendar(id=uuid4())
        mock_calendar_repo.save.return_value = saved

        result = await calendar_service.create_calendar(
            calendar, transaction=mock_transaction
        )

        assert result is saved
        mock_calendar_repo.save.assert_awaited_once_with(calendar)


class TestUpdateCalendar:
    """Test the update_calendar unit of work."""

    @pytest.mark.asyncio
    async def test_update_calendar_persists_and_returns(
        self, calendar_service, mock_calendar_repo, mock_transaction
    ):
        """update_calendar saves via the repo and returns the saved entity."""
        calendar = _calendar(id=uuid4(), name="Renamed")
        mock_calendar_repo.save.return_value = calendar

        result = await calendar_service.update_calendar(
            calendar, transaction=mock_transaction
        )

        assert result is calendar
        mock_calendar_repo.save.assert_awaited_once_with(calendar)


class TestDeleteCalendar:
    """Test the delete_calendar unit of work."""

    @staticmethod
    def _transaction_with_usage(usage_count: int) -> AsyncMock:
        """Build a mock transaction whose usage query returns ``usage_count``."""
        transaction = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = (usage_count,)
        transaction.execute.return_value = result
        return transaction

    @pytest.mark.asyncio
    async def test_delete_calendar_deletes_when_unused(
        self, calendar_service, mock_calendar_repo
    ):
        """delete_calendar removes the calendar when no journals reference it."""
        calendar_id = uuid4()
        calendar = _calendar(id=calendar_id)
        transaction = self._transaction_with_usage(0)

        await calendar_service.delete_calendar(
            calendar, user_id="user-1", transaction=transaction
        )

        mock_calendar_repo.delete.assert_awaited_once_with(calendar_id)

    @pytest.mark.asyncio
    async def test_delete_calendar_rejects_non_owner(
        self, calendar_service, mock_calendar_repo, mock_transaction
    ):
        """delete_calendar raises a permission error for a non-owner."""
        calendar = _calendar(id=uuid4(), user_id="owner")

        with pytest.raises(CalendarPermissionError):
            await calendar_service.delete_calendar(
                calendar, user_id="someone-else", transaction=mock_transaction
            )

        mock_calendar_repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_calendar_rejects_unsaved_calendar(
        self, calendar_service, mock_calendar_repo, mock_transaction
    ):
        """An unsaved calendar (id=None) fails up front, before the usage query."""
        calendar = _calendar(id=None)

        with pytest.raises(CalendarNotFoundError):
            await calendar_service.delete_calendar(
                calendar, user_id="user-1", transaction=mock_transaction
            )

        # Deterministic failure: no usage-count query with a NULL id, no delete.
        mock_transaction.execute.assert_not_awaited()
        mock_calendar_repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_calendar_rejects_in_use(
        self, calendar_service, mock_calendar_repo
    ):
        """delete_calendar raises an in-use error when journals reference it."""
        calendar = _calendar(id=uuid4())
        transaction = self._transaction_with_usage(2)

        with pytest.raises(CalendarInUseError):
            await calendar_service.delete_calendar(
                calendar, user_id="user-1", transaction=transaction
            )

        mock_calendar_repo.delete.assert_not_awaited()
