# ruff: noqa: E402
"""Tests for Snipe-IT sync service outbound maintenance methods."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_sync_service import (
    SnipeItSyncService,
    _format_date_for_snipeit,
    _local_date,
    _resolve_zone,
    _snipeit_checkin_at,
    _usage_period_has_ended,
)

SYDNEY = "Australia/Sydney"


class TestResolveZone:
    """Snipe dates are read in the event's zone, then the user's, then UTC."""

    def test_event_zone_wins(self) -> None:
        assert _resolve_zone("Europe/London", SYDNEY) == "Europe/London"

    def test_invalid_event_zone_falls_back_to_user_zone(self) -> None:
        assert _resolve_zone("Not/AZone", SYDNEY) == SYDNEY

    def test_non_string_and_empty_values_are_skipped(self) -> None:
        assert _resolve_zone(MagicMock(), "") is None

    def test_no_zone_is_none(self) -> None:
        assert _resolve_zone(None, None) is None


class TestLocalDate:
    """Journal dates are local-midnight instants stored in UTC."""

    def test_sydney_daylight_time_midnight(self) -> None:
        # 2025-03-08 00:00 AEDT (+11:00)
        assert _local_date(datetime(2025, 3, 7, 13, 0, tzinfo=UTC), SYDNEY) == date(
            2025, 3, 8
        )

    def test_sydney_standard_time_midnight(self) -> None:
        # 2025-06-08 00:00 AEST (+10:00)
        assert _local_date(datetime(2025, 6, 7, 14, 0, tzinfo=UTC), SYDNEY) == date(
            2025, 6, 8
        )

    def test_sydney_morning_buffer_time(self) -> None:
        # A datetime-local checkout of 2025-03-08 08:00 AEDT
        assert _local_date(datetime(2025, 3, 7, 21, 0, tzinfo=UTC), SYDNEY) == date(
            2025, 3, 8
        )

    def test_event_zone_other_than_sydney(self) -> None:
        # 23:30 on the 7th in London is already the 8th in Sydney.
        instant = datetime(2025, 3, 7, 23, 30, tzinfo=UTC)
        zone = _resolve_zone("Europe/London", SYDNEY)
        assert _local_date(instant, zone) == date(2025, 3, 7)

    def test_no_zone_uses_utc(self) -> None:
        assert _local_date(datetime(2025, 3, 7, 13, 0, tzinfo=UTC), None) == date(
            2025, 3, 7
        )

    def test_plain_date_and_iso_string_pass_through(self) -> None:
        assert _local_date(date(2025, 3, 8), SYDNEY) == date(2025, 3, 8)
        assert _local_date("2025-03-08", SYDNEY) == date(2025, 3, 8)

    def test_none_and_unparseable_are_none(self) -> None:
        assert _local_date(None, SYDNEY) is None
        assert _local_date("not a date", SYDNEY) is None

    def test_format_uses_local_date(self) -> None:
        assert (
            _format_date_for_snipeit(datetime(2025, 3, 7, 13, 0, tzinfo=UTC), SYDNEY)
            == "2025-03-08"
        )


class TestSnipeitCheckinAt:
    """Snipe-IT must never be sent a check-in date its server reads as the future.

    The server's zone is unknown, so a date is only sent once it has passed in
    the earliest zone (UTC-12), where "today" is earliest.
    """

    # 2025-03-08 08:00 in Sydney; 2025-03-07 09:00 at UTC-12.
    NOW = datetime(2025, 3, 7, 21, 0, tzinfo=UTC)

    def test_historical_date_is_sent(self) -> None:
        assert _snipeit_checkin_at(date(2019, 5, 4), now=self.NOW) == date(2019, 5, 4)

    def test_date_already_past_everywhere_is_sent(self) -> None:
        assert _snipeit_checkin_at(date(2025, 3, 6), now=self.NOW) == date(2025, 3, 6)

    def test_date_still_today_at_utc_minus_12_is_omitted(self) -> None:
        # Yesterday in Sydney, but a server at UTC-12 is still on the 7th.
        assert _snipeit_checkin_at(date(2025, 3, 7), now=self.NOW) is None

    def test_local_today_is_omitted(self) -> None:
        assert _snipeit_checkin_at(date(2025, 3, 8), now=self.NOW) is None

    def test_none_is_none(self) -> None:
        assert _snipeit_checkin_at(None, now=self.NOW) is None


class TestUsagePeriodHasEnded:
    """The check-in trigger predicate compares full timestamps (not date-only)."""

    def test_none_is_not_past(self) -> None:
        assert _usage_period_has_ended(None) is False

    def test_datetime_earlier_today_is_past(self) -> None:
        """A timestamp earlier *today* counts as past (the date-only bug)."""
        now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        earlier_today = datetime(2026, 6, 30, 2, 0, tzinfo=UTC)
        assert _usage_period_has_ended(earlier_today, now=now) is True

    def test_datetime_later_today_is_not_past(self) -> None:
        now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        later_today = datetime(2026, 6, 30, 18, 0, tzinfo=UTC)
        assert _usage_period_has_ended(later_today, now=now) is False

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        naive_past = datetime(2026, 6, 30, 2, 0)
        assert _usage_period_has_ended(naive_past, now=now) is True

    def test_past_date_is_past(self) -> None:
        now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        assert _usage_period_has_ended(date(2026, 6, 29), now=now) is True

    def test_future_datetime_is_not_past(self) -> None:
        now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        assert _usage_period_has_ended(now + timedelta(days=1), now=now) is False


def _mock_api_client() -> AsyncMock:
    """Create a mock SnipeItAPIClient."""
    client = AsyncMock(spec=SnipeItAPIClient)
    return client


def _mock_session_factory(
    *,
    journal_row: MagicMock | None = None,
    maintenance_data_row: MagicMock | None = None,
    asset_sync_meta_row: MagicMock | None = None,
    maintenance_sync_meta_row: MagicMock | None = None,
) -> MagicMock:
    """Build a mock session factory that returns different rows for sequential queries.

    The push_maintenance_create method executes these queries in order:
      1. SELECT from journals (title, content, dates)
      2. SELECT from journal_gear_maintenance_data
      3. SELECT from sync_metadata (asset → Snipe-IT ID)
    """
    mock_session = AsyncMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    # Build result sequence for sequential execute calls
    results = []

    # Query 1: journal data
    journal_result = MagicMock()
    journal_result.fetchone.return_value = journal_row
    results.append(journal_result)

    # Query 2: gear maintenance data
    maintenance_result = MagicMock()
    maintenance_result.fetchone.return_value = maintenance_data_row
    results.append(maintenance_result)

    # Query 3: asset sync metadata
    asset_meta_result = MagicMock()
    asset_meta_result.fetchone.return_value = asset_sync_meta_row
    results.append(asset_meta_result)

    # Query 4: maintenance sync metadata (for create: check existing)
    if maintenance_sync_meta_row is not None:
        maint_meta_result = MagicMock()
        maint_meta_result.fetchone.return_value = maintenance_sync_meta_row
        results.append(maint_meta_result)

    mock_session.execute = AsyncMock(side_effect=results)

    # Begin context manager
    mock_begin = MagicMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin.return_value = mock_begin

    factory = MagicMock(return_value=mock_session_ctx)
    return factory


class TestPushMaintenanceCreate:
    """Tests for push_maintenance_create method."""

    @pytest.mark.asyncio
    async def test_creates_maintenance_in_snipeit(self) -> None:
        """Happy path: creates maintenance record via POST and saves sync metadata."""
        api_client = _mock_api_client()
        api_client.create_maintenance.return_value = MagicMock(id=201)

        journal_row = MagicMock(
            title="Rope Inspection",
            content="All good",
            event_date_range_start=datetime(2024, 6, 1, tzinfo=UTC),
            event_date_range_end=datetime(2024, 6, 2, 14, 30, tzinfo=UTC),
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="routine inspection",
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        # First session_factory() call: _fetch_journal_and_maintenance_data (3 queries)
        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)

        fetch_results = [
            MagicMock(fetchone=MagicMock(return_value=journal_row)),
            MagicMock(fetchone=MagicMock(return_value=maintenance_data_row)),
            MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            MagicMock(fetchone=MagicMock(return_value=None)),  # not imported
        ]
        first_session.execute = AsyncMock(side_effect=fetch_results)

        # Second session_factory() call: check if already synced
        second_session = AsyncMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_2 = MagicMock()
        mock_begin_2.__aenter__ = AsyncMock(return_value=None)
        mock_begin_2.__aexit__ = AsyncMock(return_value=False)
        second_session.begin = MagicMock(return_value=mock_begin_2)
        second_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )

        # Third session_factory() call: save sync metadata (with begin())
        third_session = MagicMock()
        third_session_ctx = MagicMock()
        third_session_ctx.__aenter__ = AsyncMock(return_value=third_session)
        third_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        third_session.begin = MagicMock(return_value=mock_begin)
        third_session.execute = AsyncMock()

        session_factory = MagicMock(
            side_effect=[first_session_ctx, second_session_ctx, third_session_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_create(
            journal_id=100,
            session_factory=session_factory,
        )

        # Verify API was called with correct asset_id and payload
        api_client.create_maintenance.assert_called_once()
        call_args = api_client.create_maintenance.call_args
        assert call_args.kwargs["asset_id"] == 42
        payload = call_args.kwargs["payload"]
        assert payload["name"] == "Rope Inspection"
        assert payload["asset_maintenance_type"] == "PAT Test"  # routine inspection
        # Dates must be YYYY-MM-DD format for Snipe-IT API
        assert payload["start_date"] == "2024-06-01"
        assert payload["completion_date"] == "2024-06-02"

    @pytest.mark.asyncio
    async def test_skips_when_no_journal_found(self) -> None:
        """No journal row means we skip silently."""
        api_client = _mock_api_client()

        session_factory = _mock_session_factory(
            journal_row=None,
            maintenance_data_row=None,
            asset_sync_meta_row=None,
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.create_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_maintenance_data(self) -> None:
        """Journal exists but no gear maintenance data means skip."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Some Journal",
            content="",
            event_date_range_start=None,
            event_date_range_end=None,
        )

        session_factory = _mock_session_factory(
            journal_row=journal_row,
            maintenance_data_row=None,
            asset_sync_meta_row=None,
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.create_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_asset_sync_metadata(self) -> None:
        """Gear item not synced to Snipe-IT yet means skip."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-01",
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="routine maintenance",
        )

        session_factory = _mock_session_factory(
            journal_row=journal_row,
            maintenance_data_row=maintenance_data_row,
            asset_sync_meta_row=None,
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.create_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_invalid_asset_external_id(self) -> None:
        """Non-numeric asset external_id is handled gracefully."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start=datetime(2024, 6, 1, tzinfo=UTC),
            event_date_range_end=datetime(2024, 6, 1, tzinfo=UTC),
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="routine maintenance",
        )
        asset_sync_meta_row = MagicMock(external_id="not-a-number")

        # First session: fetch data (3 queries)
        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)
        first_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=maintenance_data_row)),
                MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
                MagicMock(fetchone=MagicMock(return_value=None)),  # not imported
            ]
        )

        # Second session: dedup check
        second_session = AsyncMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_2 = MagicMock()
        mock_begin_2.__aenter__ = AsyncMock(return_value=None)
        mock_begin_2.__aexit__ = AsyncMock(return_value=False)
        second_session.begin = MagicMock(return_value=mock_begin_2)
        second_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )

        third_session = MagicMock()
        third_session_ctx = MagicMock()
        third_session_ctx.__aenter__ = AsyncMock(return_value=third_session)
        third_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_3 = MagicMock()
        mock_begin_3.__aenter__ = AsyncMock(return_value=None)
        mock_begin_3.__aexit__ = AsyncMock(return_value=False)
        third_session.begin = MagicMock(return_value=mock_begin_3)
        third_session.execute = AsyncMock()
        session_factory = MagicMock(
            side_effect=[first_session_ctx, second_session_ctx, third_session_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.create_maintenance.assert_not_called()


class TestPushMaintenanceUpdate:
    """Tests for push_maintenance_update method."""

    @pytest.mark.asyncio
    async def test_updates_maintenance_in_snipeit(self) -> None:
        """Happy path: patches maintenance record via PATCH."""
        api_client = _mock_api_client()
        api_client.update_maintenance.return_value = MagicMock(id=201)

        journal_row = MagicMock(
            title="Updated Inspection",
            content="New notes",
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-03",
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="repairing gear",
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        # For update, we need a 4th query result: maintenance sync metadata
        mock_session = MagicMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        maint_sync_row = MagicMock(external_id="snipeit_maint:201")

        # Set up results for the 4 queries + 1 metadata update
        results = [
            MagicMock(fetchone=MagicMock(return_value=journal_row)),  # journal
            MagicMock(
                fetchone=MagicMock(return_value=maintenance_data_row)
            ),  # maintenance data
            MagicMock(
                fetchone=MagicMock(return_value=asset_sync_meta_row)
            ),  # asset sync
            MagicMock(fetchone=MagicMock(return_value=None)),  # not imported
            MagicMock(
                fetchone=MagicMock(return_value=maint_sync_row)
            ),  # maintenance sync
            MagicMock(),  # metadata UPDATE result
        ]
        mock_session.execute = AsyncMock(side_effect=results)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_begin

        session_factory = MagicMock(return_value=mock_session_ctx)

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_update(
            journal_id=100,
            session_factory=session_factory,
        )

        # Verify PATCH was called
        api_client.update_maintenance.assert_called_once()
        call_args = api_client.update_maintenance.call_args
        assert call_args.args[0] == 201  # maintenance_id
        payload = call_args.args[1]
        assert payload["name"] == "Updated Inspection"
        assert payload["asset_maintenance_type"] == "Repair"

        # Verify sync metadata was updated (6th execute call)
        assert mock_session.execute.call_count == 6

    @pytest.mark.asyncio
    async def test_skips_when_no_maintenance_sync_metadata(self) -> None:
        """No existing maintenance sync metadata means skip (was never synced to Snipe-IT)."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-01",
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="routine maintenance",
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        # No maintenance sync row
        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        results = [
            MagicMock(fetchone=MagicMock(return_value=journal_row)),
            MagicMock(fetchone=MagicMock(return_value=maintenance_data_row)),
            MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            MagicMock(fetchone=MagicMock(return_value=None)),  # not imported
            MagicMock(fetchone=MagicMock(return_value=None)),  # no maint sync
        ]
        mock_session.execute = AsyncMock(side_effect=results)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_begin

        session_factory = MagicMock(return_value=mock_session_ctx)

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        await service.push_maintenance_update(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.update_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_api_404(self) -> None:
        """404 from Snipe-IT during update logs and returns (doesn't raise)."""
        api_client = _mock_api_client()
        api_client.update_maintenance.side_effect = SnipeItAPIError(
            "Not found", status_code=404
        )

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-01",
        )
        maintenance_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            maintenance_type="routine maintenance",
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        maint_sync_row = MagicMock(external_id="snipeit_maint:201")

        results = [
            MagicMock(fetchone=MagicMock(return_value=journal_row)),
            MagicMock(fetchone=MagicMock(return_value=maintenance_data_row)),
            MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            MagicMock(fetchone=MagicMock(return_value=None)),  # not imported
            MagicMock(fetchone=MagicMock(return_value=maint_sync_row)),
        ]
        mock_session.execute = AsyncMock(side_effect=results)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_begin

        session_factory = MagicMock(return_value=mock_session_ctx)

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
        )

        # Should not raise
        await service.push_maintenance_update(
            journal_id=100,
            session_factory=session_factory,
        )


def _sql_routed_session_factory(rows: dict[str, object]) -> MagicMock:
    """A session factory whose queries return the row mapped to a SQL fragment.

    Each ``execute`` returns the row of the first key found in the statement
    text, or ``None``. Routing by statement rather than call order means a query
    added or reordered cannot hand another query's row to the code under test.
    """

    async def execute(
        statement: object, *_args: object, **_kwargs: object
    ) -> MagicMock:
        sql = str(statement)
        row = next((value for key, value in rows.items() if key in sql), None)
        return MagicMock(fetchone=MagicMock(return_value=row))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    begin = MagicMock()
    begin.__aenter__ = AsyncMock(return_value=None)
    begin.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin)
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session_ctx)


class TestPushMaintenanceSkipsImportedJournals:
    """A journal imported from Snipe-IT must never be written back to it."""

    @staticmethod
    def _imported_journal_rows(**extra: object) -> dict[str, object]:
        return {
            "FROM journals j": MagicMock(
                title="Split Canyoneroo 50 -> 34 + 15",
                content="",
                event_date_range_start=datetime(2026, 9, 11, tzinfo=UTC),
                event_date_range_end=datetime(2026, 9, 11, tzinfo=UTC),
            ),
            "FROM journal_gear_maintenance_data": MagicMock(
                gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                maintenance_type="routine maintenance",
            ),
            "integration_source = 'snipeit'\n": MagicMock(external_id="51"),
            "journal_external_event_links": (1,),
            **extra,
        }

    @pytest.mark.asyncio
    async def test_create_does_not_post(self) -> None:
        api_client = _mock_api_client()
        api_client.create_maintenance.return_value = MagicMock(id=20)
        service = SnipeItSyncService(api_client=api_client, user_id="user-1")

        await service.push_maintenance_create(
            journal_id=215032,
            session_factory=_sql_routed_session_factory(self._imported_journal_rows()),
        )

        api_client.create_maintenance.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_does_not_patch_an_echo(self) -> None:
        """An already-echoed journal carries a push row, yet must not PATCH it."""
        api_client = _mock_api_client()
        service = SnipeItSyncService(api_client=api_client, user_id="user-1")
        rows = self._imported_journal_rows(
            **{"'snipeit_maintenance'": MagicMock(external_id="snipeit_maint:20")}
        )

        await service.push_maintenance_update(
            journal_id=215032,
            session_factory=_sql_routed_session_factory(rows),
        )

        api_client.update_maintenance.assert_not_called()


class TestPushCheckoutCreate:
    """Tests for push_checkout_create method."""

    @pytest.mark.asyncio
    async def test_creates_checkout_in_snipeit(self) -> None:
        """Happy path: posts checkout to Snipe-IT and saves sync metadata."""
        api_client = _mock_api_client()
        api_client.checkout_asset.return_value = {
            "status": "success",
            "messages": "Asset checked out successfully.",
        }

        # Future dates keep this focused on the checkout path (a past checkin
        # date would additionally trigger an immediate check-in).
        journal_row = MagicMock(
            title="Rope usage at crag",
            content="Used climbing rope",
            event_date_range_start=datetime(2099, 6, 1, tzinfo=UTC),
            event_date_range_end=datetime(2099, 6, 2, 14, 30, tzinfo=UTC),
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=datetime(2099, 6, 1, 8, 0, tzinfo=UTC),
            checkin_date=datetime(2099, 6, 2, 18, 0, tzinfo=UTC),
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        # First session_factory() call: _fetch_journal_and_gear_usage_data (3 queries)
        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)

        fetch_results = [
            MagicMock(fetchone=MagicMock(return_value=journal_row)),
            MagicMock(fetchone=MagicMock(return_value=usage_data_row)),
            MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
        ]
        first_session.execute = AsyncMock(side_effect=fetch_results)

        # Second session_factory() call: check if already synced
        second_session = AsyncMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_2 = MagicMock()
        mock_begin_2.__aenter__ = AsyncMock(return_value=None)
        mock_begin_2.__aexit__ = AsyncMock(return_value=False)
        second_session.begin = MagicMock(return_value=mock_begin_2)
        second_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )

        # Third session_factory() call: save sync metadata (with begin())
        third_session = MagicMock()
        third_session_ctx = MagicMock()
        third_session_ctx.__aenter__ = AsyncMock(return_value=third_session)
        third_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        third_session.begin = MagicMock(return_value=mock_begin)
        third_session.execute = AsyncMock()

        session_factory = MagicMock(
            side_effect=[first_session_ctx, second_session_ctx, third_session_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )

        # Verify API was called with correct payload
        api_client.checkout_asset.assert_called_once()
        call_args = api_client.checkout_asset.call_args
        assert call_args.kwargs["asset_id"] == 42
        payload = call_args.kwargs["payload"]
        assert payload["assigned_user"] == "5"
        assert payload["checkout_to_type"] == "user"
        assert payload["checkout_at"] == "2099-06-01"
        assert payload["expected_checkin"] == "2099-06-02"
        assert payload["note"] == "Rope usage at crag"

    @pytest.mark.asyncio
    async def test_skips_when_no_journal_found(self) -> None:
        """No journal row means we skip silently."""
        api_client = _mock_api_client()

        session_factory = _mock_session_factory(
            journal_row=None,
            maintenance_data_row=None,
            asset_sync_meta_row=None,
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.checkout_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_usage_data(self) -> None:
        """Journal exists but no gear usage data means skip."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Some Journal",
            content="",
            event_date_range_start=None,
            event_date_range_end=None,
        )

        # Build a mock that returns journal_row then None for usage data
        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)

        first_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=None)),
            ]
        )

        session_factory = MagicMock(return_value=first_session_ctx)

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.checkout_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_asset_sync_metadata(self) -> None:
        """Gear item not synced to Snipe-IT yet means skip."""
        api_client = _mock_api_client()

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-01",
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=None,
            checkin_date=None,
        )

        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)
        first_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=usage_data_row)),
                MagicMock(fetchone=MagicMock(return_value=None)),
            ]
        )

        session_factory = MagicMock(return_value=first_session_ctx)

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )

        api_client.checkout_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_journal_dates_when_buffer_dates_absent(self) -> None:
        """When checkout/checkin dates are None, falls back to journal date range."""
        api_client = _mock_api_client()
        api_client.checkout_asset.return_value = {"status": "success"}

        journal_row = MagicMock(
            title="Usage log",
            content="",
            event_date_range_start=datetime(2099, 7, 10, tzinfo=UTC),
            event_date_range_end=datetime(2099, 7, 12, tzinfo=UTC),
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=None,
            checkin_date=None,
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)
        first_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=usage_data_row)),
                MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            ]
        )

        second_session = AsyncMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_2 = MagicMock()
        mock_begin_2.__aenter__ = AsyncMock(return_value=None)
        mock_begin_2.__aexit__ = AsyncMock(return_value=False)
        second_session.begin = MagicMock(return_value=mock_begin_2)
        second_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )

        third_session = MagicMock()
        third_session_ctx = MagicMock()
        third_session_ctx.__aenter__ = AsyncMock(return_value=third_session)
        third_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        third_session.begin = MagicMock(return_value=mock_begin)
        third_session.execute = AsyncMock()

        session_factory = MagicMock(
            side_effect=[first_session_ctx, second_session_ctx, third_session_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )

        call_args = api_client.checkout_asset.call_args
        payload = call_args.kwargs["payload"]
        assert payload["checkout_at"] == "2099-07-10"
        assert payload["expected_checkin"] == "2099-07-12"

    @pytest.mark.asyncio
    async def test_handles_api_404(self) -> None:
        """404 from Snipe-IT during checkout logs and returns (doesn't raise)."""
        api_client = _mock_api_client()
        api_client.checkout_asset.side_effect = SnipeItAPIError(
            "Not found", status_code=404
        )

        journal_row = MagicMock(
            title="Test",
            content="",
            event_date_range_start=datetime(2024, 6, 1, tzinfo=UTC),
            event_date_range_end=datetime(2024, 6, 1, tzinfo=UTC),
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=None,
            checkin_date=None,
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        first_session = AsyncMock()
        first_session_ctx = MagicMock()
        first_session_ctx.__aenter__ = AsyncMock(return_value=first_session)
        first_session_ctx.__aexit__ = AsyncMock(return_value=False)
        first_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=usage_data_row)),
                MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            ]
        )

        second_session = AsyncMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_2 = MagicMock()
        mock_begin_2.__aenter__ = AsyncMock(return_value=None)
        mock_begin_2.__aexit__ = AsyncMock(return_value=False)
        second_session.begin = MagicMock(return_value=mock_begin_2)
        second_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )

        third_session = MagicMock()
        third_session_ctx = MagicMock()
        third_session_ctx.__aenter__ = AsyncMock(return_value=third_session)
        third_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_begin_3 = MagicMock()
        mock_begin_3.__aenter__ = AsyncMock(return_value=None)
        mock_begin_3.__aexit__ = AsyncMock(return_value=False)
        third_session.begin = MagicMock(return_value=mock_begin_3)
        third_session.execute = AsyncMock()
        session_factory = MagicMock(
            side_effect=[first_session_ctx, second_session_ctx, third_session_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client,
            user_id="user-1",
            snipeit_user_id="5",
        )

        # Should not raise
        await service.push_checkout_create(
            journal_id=100,
            session_factory=session_factory,
        )


def _checkin_resolve_ctx(checkout_row: MagicMock | None) -> MagicMock:
    """Session context for the checkout-metadata resolution query (no begin)."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(
        side_effect=[MagicMock(fetchone=MagicMock(return_value=checkout_row))]
    )
    return ctx


def _begin_session_ctx(execute_results: list[MagicMock]) -> MagicMock:
    """Session context that uses ``session.begin()`` and the given execute results."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    begin = MagicMock()
    begin.__aenter__ = AsyncMock(return_value=None)
    begin.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin)
    session.execute = AsyncMock(side_effect=execute_results)
    return ctx


class TestPushCheckinCreate:
    """Tests for push_checkin_create method."""

    @pytest.mark.asyncio
    async def test_creates_checkin_when_checkout_successful(self) -> None:
        """Happy path: resolves the asset from checkout metadata and checks it in."""
        api_client = _mock_api_client()
        api_client.checkin_asset.return_value = {"status": "success"}

        checkout_row = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="success"
        )

        # 1: resolve checkout metadata; 2: lock checkin (no existing → insert);
        # 3: mark success.
        lock_ctx = _begin_session_ctx(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )
        success_ctx = _begin_session_ctx([MagicMock()])

        session_factory = MagicMock(
            side_effect=[_checkin_resolve_ctx(checkout_row), lock_ctx, success_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        result = await service.push_checkin_create(
            journal_id=100, session_factory=session_factory, note="Returned from trip"
        )

        assert result is True  # an actual check-in was performed
        api_client.checkin_asset.assert_called_once()
        call_args = api_client.checkin_asset.call_args
        assert call_args.kwargs["asset_id"] == 42
        # Without a historical date Snipe-IT stamps the check-in now.
        assert call_args.kwargs["payload"] == {"note": "Returned from trip"}

    @pytest.mark.asyncio
    async def test_sends_historical_checkin_at(self) -> None:
        """A known return date is sent as ``checkin_at`` so Snipe-IT backdates it."""
        api_client = _mock_api_client()
        api_client.checkin_asset.return_value = {"status": "success"}

        checkout_row = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="success"
        )
        lock_ctx = _begin_session_ctx(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )
        success_ctx = _begin_session_ctx([MagicMock()])
        session_factory = MagicMock(
            side_effect=[_checkin_resolve_ctx(checkout_row), lock_ctx, success_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        await service.push_checkin_create(
            journal_id=100,
            session_factory=session_factory,
            note="Usage period 2019-05-01 to 2019-05-04",
            checkin_at=date(2019, 5, 4),
        )

        assert api_client.checkin_asset.call_args.kwargs["payload"] == {
            "note": "Usage period 2019-05-01 to 2019-05-04",
            "checkin_at": "2019-05-04",
        }

    @pytest.mark.asyncio
    async def test_skips_when_no_checkout_metadata(self) -> None:
        """No recorded checkout means there is nothing to check in."""
        api_client = _mock_api_client()
        session_factory = MagicMock(return_value=_checkin_resolve_ctx(None))

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        result = await service.push_checkin_create(
            journal_id=100, session_factory=session_factory
        )

        assert result is False  # no-op
        api_client.checkin_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_checkout_not_successful(self) -> None:
        """A non-success checkout (e.g. failed) is not checked in."""
        api_client = _mock_api_client()
        checkout_row = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="failed"
        )
        session_factory = MagicMock(return_value=_checkin_resolve_ctx(checkout_row))

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        await service.push_checkin_create(
            journal_id=100, session_factory=session_factory
        )

        api_client.checkin_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_already_checked_in(self) -> None:
        """An existing successful checkin row makes the call idempotent."""
        api_client = _mock_api_client()
        checkout_row = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="success"
        )
        existing_checkin = MagicMock(sync_status="success", age_seconds=10.0)
        lock_ctx = _begin_session_ctx(
            [MagicMock(fetchone=MagicMock(return_value=existing_checkin))]
        )

        session_factory = MagicMock(
            side_effect=[_checkin_resolve_ctx(checkout_row), lock_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        await service.push_checkin_create(
            journal_id=100, session_factory=session_factory
        )

        api_client.checkin_asset.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_api_404_terminal(self) -> None:
        """404 is terminal: finalized (not retried) and returns False, no raise."""
        api_client = _mock_api_client()
        api_client.checkin_asset.side_effect = SnipeItAPIError(
            "Not found", status_code=404
        )
        checkout_row = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="success"
        )
        lock_ctx = _begin_session_ctx(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )
        # Third session is the terminal _finalize_checkin (success), not a retryable unlock.
        finalize_ctx = _begin_session_ctx([MagicMock()])

        session_factory = MagicMock(
            side_effect=[_checkin_resolve_ctx(checkout_row), lock_ctx, finalize_ctx]
        )

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        # Should not raise; 404 is a terminal no-op.
        result = await service.push_checkin_create(
            journal_id=100, session_factory=session_factory
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_immediate_checkin_when_checkout_period_already_past(self) -> None:
        """A checkout whose checkin date is already past is immediately checked in."""
        api_client = _mock_api_client()
        api_client.checkout_asset.return_value = {"status": "success"}
        api_client.checkin_asset.return_value = {"status": "success"}

        # Unmistakably far-past checkin date (time-independent) → push_checkout_create
        # should chain a check-in.
        journal_row = MagicMock(
            title="Past trip",
            content="",
            event_date_range_start=datetime(2000, 1, 1, tzinfo=UTC),
            event_date_range_end=datetime(2000, 1, 2, tzinfo=UTC),
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=datetime(2000, 1, 1, tzinfo=UTC),
            checkin_date=datetime(2000, 1, 2, tzinfo=UTC),
        )
        asset_sync_meta_row = MagicMock(external_id="42")

        # Checkout: fetch (3 queries) → lock (begin) → mark success (begin).
        fetch_session = AsyncMock()
        fetch_ctx = MagicMock()
        fetch_ctx.__aenter__ = AsyncMock(return_value=fetch_session)
        fetch_ctx.__aexit__ = AsyncMock(return_value=False)
        fetch_session.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchone=MagicMock(return_value=journal_row)),
                MagicMock(fetchone=MagicMock(return_value=usage_data_row)),
                MagicMock(fetchone=MagicMock(return_value=asset_sync_meta_row)),
            ]
        )
        checkout_lock_ctx = _begin_session_ctx(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )
        checkout_success_ctx = _begin_session_ctx([MagicMock()])

        # Immediate check-in: resolve checkout meta → lock → mark success.
        checkout_meta = MagicMock(
            external_id="snipeit_checkout:42:100", sync_status="success"
        )
        checkin_resolve_ctx = _checkin_resolve_ctx(checkout_meta)
        checkin_lock_ctx = _begin_session_ctx(
            [
                MagicMock(fetchone=MagicMock(return_value=None)),
                MagicMock(fetchone=MagicMock(return_value=(1,))),
            ]
        )
        checkin_success_ctx = _begin_session_ctx([MagicMock()])

        session_factory = MagicMock(
            side_effect=[
                fetch_ctx,
                checkout_lock_ctx,
                checkout_success_ctx,
                checkin_resolve_ctx,
                checkin_lock_ctx,
                checkin_success_ctx,
            ]
        )

        service = SnipeItSyncService(
            api_client=api_client, user_id="user-1", snipeit_user_id="5"
        )

        await service.push_checkout_create(
            journal_id=100, session_factory=session_factory
        )

        api_client.checkout_asset.assert_called_once()
        api_client.checkin_asset.assert_called_once()
        assert api_client.checkin_asset.call_args.kwargs["asset_id"] == 42
