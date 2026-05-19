# ruff: noqa: E402
"""Tests for Snipe-IT sync service outbound maintenance methods."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

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
            event_date_range_start="2024-06-01",
            event_date_range_end="2024-06-02",
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

        # Second session_factory() call: save sync metadata (with begin())
        second_session = MagicMock()
        second_session_ctx = MagicMock()
        second_session_ctx.__aenter__ = AsyncMock(return_value=second_session)
        second_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_begin = MagicMock()
        mock_begin.__aenter__ = AsyncMock(return_value=None)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        second_session.begin.return_value = mock_begin
        second_session.execute = AsyncMock()

        session_factory = MagicMock(side_effect=[first_session_ctx, second_session_ctx])

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
        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        maint_sync_row = MagicMock(external_id="snipeit_maint:201")

        # Set up results for the 4 queries
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
