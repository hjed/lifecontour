"""Unit tests for JournalSeriesService."""

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalNotFoundError,
    JournalSeriesNotFoundError,
    JournalValidationError,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.services.journal_series_service import JournalSeriesService

USER_ID = "user-1"
OTHER_USER_ID = "user-2"

# @transactional treats a non-AsyncConnection as "no transaction management";
# the cast keeps unit tests honest about the service signature without a DB.
NO_TRANSACTION = cast(AsyncConnection, None)


def _series_uuid(series: JournalSeries) -> uuid.UUID:
    assert series.id is not None
    return series.id


def _make_series(**overrides: object) -> JournalSeries:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": USER_ID,
        "name": "Physio appointments",
    }
    defaults.update(overrides)
    return JournalSeries(**defaults)  # type: ignore[arg-type]


def _make_journal(journal_id: int = 1, user_id: str = USER_ID) -> Journal:
    return Journal(
        id=journal_id,
        user_id=user_id,
        title="Physio session",
        content="",
        event_date_range=EventDateRange(
            start=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
            end=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        ),
    )


@pytest.fixture
def series_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def journal_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(series_repo: AsyncMock, journal_repo: AsyncMock) -> JournalSeriesService:
    return JournalSeriesService(series_repo=series_repo, journal_repo=journal_repo)


class TestJournalSeriesEntity:
    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name"):
            JournalSeries(user_id=USER_ID, name="   ")

    def test_rejects_name_over_500_chars(self) -> None:
        with pytest.raises(ValueError, match="500"):
            JournalSeries(user_id=USER_ID, name="x" * 501)

    def test_auto_created_when_recurring_event_id_present(self) -> None:
        manual = _make_series()
        synced = _make_series(calendar_id=uuid.uuid4(), recurring_event_id="master123")
        assert manual.auto_created is False
        assert synced.auto_created is True


class TestCreateSeries:
    async def test_create_series_persists_via_repository(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        series = _make_series(id=None)
        saved = _make_series()
        series_repo.save.return_value = saved

        result = await service.create_series(series, transaction=NO_TRANSACTION)

        series_repo.save.assert_awaited_once_with(series)
        assert result is saved


class TestUpdateSeries:
    async def test_update_series_renames(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        existing = _make_series()
        series_repo.find_by_id.return_value = existing
        series_repo.save.side_effect = lambda s: s

        result = await service.update_series(
            series_id=_series_uuid(existing),
            user_id=USER_ID,
            name="Renamed",
            description="new description",
            transaction=NO_TRANSACTION,
        )

        series_repo.find_by_id.assert_awaited_once_with(existing.id, USER_ID)
        assert result.name == "Renamed"
        assert result.description == "new description"

    async def test_update_series_unknown_raises_not_found(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        series_repo.find_by_id.return_value = None
        series_id = uuid.uuid4()

        with pytest.raises(JournalSeriesNotFoundError):
            await service.update_series(
                series_id=series_id,
                user_id=USER_ID,
                name="Renamed",
                description=None,
                transaction=NO_TRANSACTION,
            )


class TestDeleteSeries:
    async def test_delete_series_does_not_delete_member_journals(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        existing = _make_series()
        series_repo.find_by_id.return_value = existing

        await service.delete_series(
            _series_uuid(existing), USER_ID, transaction=NO_TRANSACTION
        )

        series_repo.delete.assert_awaited_once_with(existing.id, USER_ID)
        journal_repo.delete.assert_not_called()

    async def test_delete_series_unknown_raises_not_found(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        series_repo.find_by_id.return_value = None

        with pytest.raises(JournalSeriesNotFoundError):
            await service.delete_series(
                uuid.uuid4(), USER_ID, transaction=NO_TRANSACTION
            )


class TestAddJournalToSeries:
    async def test_adds_member_when_series_and_journal_exist(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        series = _make_series()
        series_repo.find_by_id.return_value = series
        journal_repo.find_by_id.return_value = _make_journal(journal_id=42)

        await service.add_journal_to_series(
            series_id=_series_uuid(series),
            journal_id=42,
            user_id=USER_ID,
            transaction=NO_TRANSACTION,
        )

        series_repo.add_member.assert_awaited_once_with(series.id, 42)

    async def test_unknown_series_raises_not_found(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        series_repo.find_by_id.return_value = None
        journal_repo.find_by_id.return_value = _make_journal(journal_id=42)

        with pytest.raises(JournalSeriesNotFoundError):
            await service.add_journal_to_series(
                series_id=uuid.uuid4(),
                journal_id=42,
                user_id=USER_ID,
                transaction=NO_TRANSACTION,
            )
        series_repo.add_member.assert_not_called()

    async def test_unknown_journal_raises_not_found(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        series = _make_series()
        series_repo.find_by_id.return_value = series
        journal_repo.find_by_id.return_value = None

        with pytest.raises(JournalNotFoundError):
            await service.add_journal_to_series(
                series_id=_series_uuid(series),
                journal_id=42,
                user_id=USER_ID,
                transaction=NO_TRANSACTION,
            )
        series_repo.add_member.assert_not_called()

    async def test_journal_of_other_user_raises_not_found(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        series = _make_series()
        series_repo.find_by_id.return_value = series
        journal_repo.find_by_id.return_value = _make_journal(
            journal_id=42, user_id=OTHER_USER_ID
        )

        with pytest.raises(JournalNotFoundError):
            await service.add_journal_to_series(
                series_id=_series_uuid(series),
                journal_id=42,
                user_id=USER_ID,
                transaction=NO_TRANSACTION,
            )
        series_repo.add_member.assert_not_called()


class TestRemoveJournalFromSeries:
    async def test_remove_is_idempotent(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
    ) -> None:
        series = _make_series()
        series_repo.find_by_id.return_value = series

        # Repository remove_member is a no-op when the membership doesn't
        # exist; the service must not raise either time.
        await service.remove_journal_from_series(
            series_id=_series_uuid(series),
            journal_id=42,
            user_id=USER_ID,
            transaction=NO_TRANSACTION,
        )
        await service.remove_journal_from_series(
            series_id=_series_uuid(series),
            journal_id=42,
            user_id=USER_ID,
            transaction=NO_TRANSACTION,
        )

        assert series_repo.remove_member.await_count == 2

    async def test_unknown_series_raises_not_found(
        self,
        service: JournalSeriesService,
        series_repo: AsyncMock,
    ) -> None:
        series_repo.find_by_id.return_value = None

        with pytest.raises(JournalSeriesNotFoundError):
            await service.remove_journal_from_series(
                series_id=uuid.uuid4(),
                journal_id=42,
                user_id=USER_ID,
                transaction=NO_TRANSACTION,
            )


class TestUpdateSeriesValidation:
    """PR-review hardening: renames re-run entity validation."""

    async def test_update_series_rejects_blank_name(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        existing = _make_series()
        series_repo.find_by_id.return_value = existing

        with pytest.raises(JournalValidationError):
            await service.update_series(
                series_id=_series_uuid(existing),
                user_id=USER_ID,
                name="   ",
                description=None,
                transaction=NO_TRANSACTION,
            )
        series_repo.save.assert_not_called()

    async def test_update_series_rejects_name_over_500_chars(
        self, service: JournalSeriesService, series_repo: AsyncMock
    ) -> None:
        existing = _make_series()
        series_repo.find_by_id.return_value = existing

        with pytest.raises(JournalValidationError):
            await service.update_series(
                series_id=_series_uuid(existing),
                user_id=USER_ID,
                name="x" * 501,
                description=None,
                transaction=NO_TRANSACTION,
            )
        series_repo.save.assert_not_called()
