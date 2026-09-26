"""Integration tests for SqlGearUsageDataRepository."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    GearItem,
    GearUsageData,
    GearUsageItem,
    Journal,
)
from sqlalchemy import text
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


@pytest_asyncio.fixture
async def second_gear_item(
    gear_item_repository: SqlGearItemRepository,
) -> GearItem:
    """A second gear item, used on the same journal."""
    return await gear_item_repository.save(
        GearItem(user_id="test-user-123", name="Test Rope")
    )


def _uuid(gear_item: GearItem) -> UUID:
    assert gear_item.id is not None
    return UUID(gear_item.id)


def _journal_id(journal: Journal) -> int:
    assert journal.id is not None
    return journal.id


_CHECKOUT = datetime(2023, 1, 1, tzinfo=UTC)
_CHECKIN = datetime(2023, 1, 2, tzinfo=UTC)


@pytest.mark.integration
class TestSqlGearUsageDataRepository:
    """A journal's GEAR_USAGE entry and the gear items it holds."""

    async def test_save_and_find_several_items(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
        second_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        harness = GearUsageItem(
            gear_item_id=_uuid(test_gear_item),
            checkout_date=_CHECKOUT,
            checkin_date=_CHECKIN,
        )
        rope = GearUsageItem(gear_item_id=_uuid(second_gear_item))

        saved = await gear_usage_repository.save(
            GearUsageData(journal_id=journal_id, items=(harness, rope))
        )

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert found == saved
        assert found.journal_id == journal_id
        assert [
            (i.gear_item_id, i.checkout_date, i.checkin_date) for i in found.items
        ] == [
            (harness.gear_item_id, _CHECKOUT, _CHECKIN),
            (rope.gear_item_id, None, None),
        ]
        assert all(i.created_at and i.updated_at for i in found.items)
        assert found.created_at is not None

    async def test_items_keep_the_order_they_were_given_in(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
        second_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        # Whichever way the ids sort, the given order wins.
        first, second = sorted(
            (_uuid(test_gear_item), _uuid(second_gear_item)), reverse=True
        )

        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(
                    GearUsageItem(gear_item_id=first),
                    GearUsageItem(gear_item_id=second),
                ),
            )
        )

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert [i.gear_item_id for i in found.items] == [first, second]

    async def test_an_item_added_later_keeps_the_first(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
        second_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        first = GearUsageItem(gear_item_id=_uuid(test_gear_item), checkin_date=_CHECKIN)
        saved = await gear_usage_repository.save(
            GearUsageData(journal_id=journal_id, items=(first,))
        )

        await gear_usage_repository.save(
            saved.with_item(GearUsageItem(gear_item_id=_uuid(second_gear_item)))
        )

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert [(i.gear_item_id, i.checkin_date) for i in found.items] == [
            (first.gear_item_id, _CHECKIN),
            (_uuid(second_gear_item), None),
        ]
        assert found.items[0].created_at == saved.items[0].created_at

    async def test_saving_updates_an_items_dates(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        gear_item_id = _uuid(test_gear_item)
        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id, items=(GearUsageItem(gear_item_id=gear_item_id),)
            )
        )

        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(
                    GearUsageItem(gear_item_id=gear_item_id, checkout_date=_CHECKOUT),
                ),
            )
        )

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert [(i.checkout_date, i.checkin_date) for i in found.items] == [
            (_CHECKOUT, None)
        ]

    async def test_saving_without_an_item_removes_only_it(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
        second_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        saved = await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(
                    GearUsageItem(gear_item_id=_uuid(test_gear_item)),
                    GearUsageItem(gear_item_id=_uuid(second_gear_item)),
                ),
            )
        )

        await gear_usage_repository.save(saved.without_item(_uuid(test_gear_item)))

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert [i.gear_item_id for i in found.items] == [_uuid(second_gear_item)]

    async def test_an_entry_with_no_items_is_still_found(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        saved = await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(GearUsageItem(gear_item_id=_uuid(test_gear_item)),),
            )
        )

        await gear_usage_repository.save(saved.without_item(_uuid(test_gear_item)))

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert found.items == ()

    async def test_find_returns_none_if_not_found(
        self, gear_usage_repository: SqlGearUsageDataRepository
    ) -> None:
        assert await gear_usage_repository.find_by_journal_id(99999) is None

    async def test_delete_removes_the_entry_and_its_items(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        async_connection: AsyncConnection,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(GearUsageItem(gear_item_id=_uuid(test_gear_item)),),
            )
        )

        await gear_usage_repository.delete(journal_id)

        assert await gear_usage_repository.find_by_journal_id(journal_id) is None
        items = await async_connection.execute(
            text("SELECT 1 FROM journal_gear_usage_items WHERE journal_id = :id"),
            {"id": journal_id},
        )
        assert items.fetchone() is None

    async def test_cascade_delete_with_journal(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        journal_repository: SqlJournalRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(GearUsageItem(gear_item_id=_uuid(test_gear_item)),),
            )
        )

        await journal_repository.delete(journal_id)

        assert await gear_usage_repository.find_by_journal_id(journal_id) is None

    async def test_deleting_a_gear_item_removes_only_its_item(
        self,
        gear_usage_repository: SqlGearUsageDataRepository,
        gear_item_repository: SqlGearItemRepository,
        test_journal: Journal,
        test_gear_item: GearItem,
        second_gear_item: GearItem,
    ) -> None:
        journal_id = _journal_id(test_journal)
        await gear_usage_repository.save(
            GearUsageData(
                journal_id=journal_id,
                items=(
                    GearUsageItem(gear_item_id=_uuid(test_gear_item)),
                    GearUsageItem(gear_item_id=_uuid(second_gear_item)),
                ),
            )
        )

        assert test_gear_item.id is not None
        await gear_item_repository.delete(test_gear_item.id)

        found = await gear_usage_repository.find_by_journal_id(journal_id)
        assert found is not None
        assert [i.gear_item_id for i in found.items] == [_uuid(second_gear_item)]
