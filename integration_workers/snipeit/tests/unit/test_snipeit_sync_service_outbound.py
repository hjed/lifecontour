# ruff: noqa: E402
"""Tests for Snipe-IT sync service outbound maintenance methods."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_sync_service import SnipeItSyncService


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
        assert payload["title"] == "Rope Inspection"
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
        assert payload["title"] == "Updated Inspection"
        assert payload["asset_maintenance_type"] == "Repair"

        # Verify sync metadata was updated (5th execute call)
        assert mock_session.execute.call_count == 5

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

        journal_row = MagicMock(
            title="Rope usage at crag",
            content="Used climbing rope",
            event_date_range_start=datetime(2024, 6, 1, tzinfo=UTC),
            event_date_range_end=datetime(2024, 6, 2, 14, 30, tzinfo=UTC),
        )
        usage_data_row = MagicMock(
            gear_item_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            checkout_date=datetime(2024, 6, 1, 8, 0, tzinfo=UTC),
            checkin_date=datetime(2024, 6, 2, 18, 0, tzinfo=UTC),
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
        assert payload["checkout_at"] == "2024-06-01"
        assert payload["expected_checkin"] == "2024-06-02"
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
            event_date_range_start=datetime(2024, 7, 10, tzinfo=UTC),
            event_date_range_end=datetime(2024, 7, 12, tzinfo=UTC),
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
        assert payload["checkout_at"] == "2024-07-10"
        assert payload["expected_checkin"] == "2024-07-12"

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
