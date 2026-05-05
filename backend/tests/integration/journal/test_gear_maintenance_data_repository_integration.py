"""Integration tests for SqlGearMaintenanceDataRepository."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    GearItem,
    GearMaintenanceData,
    Journal,
    OutdoorActivitySubtype,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.gear_item_repository import SqlGearItemRepository
from app.core.journal.adapters.sql.gear_maintenance_data_repository import (
    SqlGearMaintenanceDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


@pytest_asyncio.fixture
async def gear_maintenance_repository(
    async_connection: AsyncConnection,
) -> SqlGearMaintenanceDataRepository:
    """Create a gear maintenance data repository for testing."""
    return SqlGearMaintenanceDataRepository(async_connection)


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
        title="Gear Maintenance",
        content="Inspected harness",
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
class TestSqlGearMaintenanceDataRepository:
    """Integration tests for SqlGearMaintenanceDataRepository."""

    async def test_save_and_find(
        self,
        gear_maintenance_repository: SqlGearMaintenanceDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test saving and finding gear maintenance data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        data = GearMaintenanceData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            maintenance_type="routine inspection",
            activity_types=[
                OutdoorActivitySubtype.CANYONING.value,
                OutdoorActivitySubtype.CLIMBING.value,
            ],
            retirement_reason=None,
        )

        # Save data
        saved_data = await gear_maintenance_repository.save(data)

        assert saved_data.journal_id == journal_id
        assert saved_data.gear_item_id == gear_item_uuid
        assert saved_data.maintenance_type == "routine inspection"
        assert saved_data.activity_types == ["canyoning", "climbing"]
        assert saved_data.retirement_reason is None
        assert saved_data.created_at is not None
        assert saved_data.updated_at is not None

        # Find data
        found_data = await gear_maintenance_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.journal_id == journal_id
        assert found_data.gear_item_id == gear_item_uuid
        assert found_data.maintenance_type == "routine inspection"
        assert found_data.activity_types == ["canyoning", "climbing"]
        assert found_data.retirement_reason is None

    async def test_save_updates_existing(
        self,
        gear_maintenance_repository: SqlGearMaintenanceDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test saving updates existing gear maintenance data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearMaintenanceData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            maintenance_type="routine maintenance",
            activity_types=[],
        )
        await gear_maintenance_repository.save(data)

        # Update data
        import dataclasses

        data = dataclasses.replace(
            data,
            maintenance_type="retiring gear",
            retirement_reason="Too worn out",
            activity_types=["caving"],
        )
        updated_data = await gear_maintenance_repository.save(data)

        assert updated_data.maintenance_type == "retiring gear"
        assert updated_data.retirement_reason == "Too worn out"
        assert updated_data.activity_types == ["caving"]

        # Verify update persisted
        found_data = await gear_maintenance_repository.find_by_journal_id(journal_id)
        assert found_data is not None
        assert found_data.maintenance_type == "retiring gear"
        assert found_data.retirement_reason == "Too worn out"
        assert found_data.activity_types == ["caving"]

    async def test_find_returns_none_if_not_found(
        self, gear_maintenance_repository: SqlGearMaintenanceDataRepository
    ) -> None:
        """Test finding non-existent data returns None."""
        found_data = await gear_maintenance_repository.find_by_journal_id(99999)
        assert found_data is None

    async def test_delete(
        self,
        gear_maintenance_repository: SqlGearMaintenanceDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test deleting gear maintenance data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearMaintenanceData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            maintenance_type="routine inspection",
        )
        await gear_maintenance_repository.save(data)

        # Delete data
        await gear_maintenance_repository.delete(journal_id)

        # Verify deleted
        found_data = await gear_maintenance_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_journal(
        self,
        gear_maintenance_repository: SqlGearMaintenanceDataRepository,
        journal_repository: SqlJournalRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test that deleting a journal cascade deletes gear maintenance data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearMaintenanceData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            maintenance_type="routine inspection",
        )
        await gear_maintenance_repository.save(data)

        # Delete journal
        await journal_repository.delete(journal_id)

        # Verify deleted
        found_data = await gear_maintenance_repository.find_by_journal_id(journal_id)
        assert found_data is None

    async def test_cascade_delete_with_gear_item(
        self,
        gear_maintenance_repository: SqlGearMaintenanceDataRepository,
        gear_item_repository: SqlGearItemRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        """Test that deleting a gear item cascade deletes gear maintenance data."""
        journal_id = test_journal.id
        gear_item_id = test_gear_item.id
        assert journal_id is not None
        assert gear_item_id is not None
        from uuid import UUID

        gear_item_uuid = UUID(gear_item_id)

        # Initial save
        data = GearMaintenanceData(
            journal_id=journal_id,
            gear_item_id=gear_item_uuid,
            maintenance_type="routine inspection",
        )
        await gear_maintenance_repository.save(data)

        # Delete gear item
        await gear_item_repository.delete(gear_item_id)

        # Verify deleted
        found_data = await gear_maintenance_repository.find_by_journal_id(journal_id)
        assert found_data is None
