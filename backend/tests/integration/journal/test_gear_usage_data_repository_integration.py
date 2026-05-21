"""Integration tests for SqlGearUsageDataRepository."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    GearItem,
    GearUsageData,
    Journal,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.gear_item_repository import SqlGearItemRepository
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def gear_usage_repository(
    async_connection: AsyncConnection,
) -> SqlGearUsageDataRepository:
    """Create a gear usage data repository for testing."""
    return SqlGearUsageDataRepository(async_connection)


@pytest_asyncio.fixture
async def gear_item_repository(
    async_connection: AsyncConnection,
) -> SqlGearItemRepository:
    """Create a gear item repository for testing."""
    return SqlGearItemRepository(async_connection)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def test_journal(
    journal_repository: SqlJournalRepository,
) -> Journal:
    """Create a test journal."""
    now = datetime.now(UTC)
    journal = Journal(
        user_id="test-user-123",
        title="Gear Usage",
        content="Used harness",
        event_date_range=EventDateRange(
            start=now,
            end=now,
        ),
    )
    return await journal_repository.save(journal)


@pytest_asyncio.fixture
async def test_gear_item(
    gear_item_repository: SqlGearItemRepository,
) -> GearItem:
    """Create a test gear item."""
    gear_item = GearItem(
        user_id="test-user-123",
        name="Test Harness",
        model="Altitude",
        manufacturer="Petzl",
    )
    return await gear_item_repository.save(gear_item)


@pytest.mark.integration
class TestSqlGearUsageDataRepository:
    """Integration tests for SqlGearUsageDataRepository."""

    async def test_save_and_find(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test saving and finding gear usage data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        checkout_date = datetime(2023, 1, 1, tzinfo=UTC)
        checkin_date = datetime(2023, 1, 2, tzinfo=UTC)

        data = GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            checkout_date=checkout_date,
            checkin_date=checkin_date,
        )

        # Save data
        saved_data = await gear_usage_repository.save(data)

        assert saved_data.journal_id == journal_id
        assert saved_data.gear_item_id == gear_item_uuid
        assert saved_data.checkout_date == checkout_date
        assert saved_data.checkin_date == checkin_date
        assert saved_data.created_at is not None
        assert saved_data.updated_at is not None

        # Find data
        found_data = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.journal_id == journal_id
        assert found_data.gear_item_id == gear_item_uuid
        assert found_data.checkout_date == checkout_date
        assert found_data.checkin_date == checkin_date

    async def test_save_updates_existing(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test saving updates existing gear usage data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            checkout_date=None,
            checkin_date=None,
        )
        await gear_usage_repository.save(data)

        # Update data
        import dataclasses

        checkout_date = datetime(2023, 1, 1, tzinfo=UTC)
        data = dataclasses.replace(
            data,
            checkout_date=checkout_date,
            checkin_date=None,
        )
        updated_data = await gear_usage_repository.save(data)

        assert updated_data.checkout_date == checkout_date
        assert updated_data.checkin_date is None

        # Verify update persisted
        found_data = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.checkout_date == checkout_date
        assert found_data.checkin_date is None

    async def test_find_returns_none_if_not_found(
        self, gear_usage_repository: SqlGearUsageDataRepository
    ) -> None:
        """Test finding non-existent data returns None."""
        found_data = await gear_usage_repository.find_by_journal_id(99999)
        assert found_data is None

    async def test_delete(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test deleting gear usage data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            checkout_date=None,
            checkin_date=None,
        )
        await gear_usage_repository.save(data)

        # Delete data
        await gear_usage_repository.delete(journal_id)

        # Verify deleted
        found_data = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_journal(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        journal_repository: SqlJournalRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test that deleting a journal cascade deletes gear usage data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            checkout_date=None,
            checkin_date=None,
        )
        await gear_usage_repository.save(data)

        # Delete journal
        await journal_repository.delete(journal_id)

        # Verify deleted
        found_data = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_gear_item(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        gear_item_repository: SqlGearItemRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test that deleting a gear item cascade deletes gear usage data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearUsageData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            checkout_date=None,
            checkin_date=None,
        )
        await gear_usage_repository.save(data)

        # Delete gear item
        await gear_item_repository.delete(gear_item_id)

        # Verify deleted
        found_data = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found_data is None
