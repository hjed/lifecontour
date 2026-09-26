"""Merging journals keeps every gear item either of them recorded.

A GEAR_USAGE entry holds a list of gear items. When both journals have one, the
target keeps its items and gains the source's (its own copy wins for a gear item
both list); when only the source has one, the entry moves across with its items.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from core_shared.models.journals import (
    EventDateRange,
    GearItem,
    GearUsageData,
    GearUsageItem,
    Journal,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.gear_item_repository import SqlGearItemRepository
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "user123"
_CHECKIN = datetime(2026, 3, 21, 9, 0, tzinfo=UTC)


@pytest.mark.integration
class TestMergeGearUsage:
    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection) -> SqlJournalRepository:
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def gear_usage_repo(
        self, clean_database: AsyncConnection
    ) -> SqlGearUsageDataRepository:
        return SqlGearUsageDataRepository(clean_database)

    @pytest.fixture
    def merge_service(
        self, journal_repo: SqlJournalRepository, clean_database: AsyncConnection
    ) -> JournalMergeService:
        return JournalMergeService(
            journal_repo=journal_repo,
            event_publisher=OutboxEventPublisher(clean_database),
            task_merge_service=TaskJournalMergeService(
                task_anchor_repo=SqlTaskAnchorRepository(clean_database),
                event_publisher=OutboxEventPublisher(clean_database),
            ),
        )

    @pytest.fixture
    async def gear(self, clean_database: AsyncConnection) -> list[UUID]:
        repo = SqlGearItemRepository(clean_database)
        ids = []
        for name in ("Rope", "Harness", "Helmet"):
            saved = await repo.save(GearItem(user_id=USER_ID, name=name))
            assert saved.id is not None
            ids.append(UUID(saved.id))
        return ids

    async def _journal(self, journal_repo: SqlJournalRepository, title: str) -> int:
        journal = await journal_repo.save(
            Journal(
                user_id=USER_ID,
                title=title,
                content="",
                event_date_range=EventDateRange(
                    start=datetime(2026, 3, 20, 8, 0), end=datetime(2026, 3, 21, 9, 0)
                ),
            )
        )
        assert journal.id is not None
        return journal.id

    async def test_both_journals_items_survive_the_merge(
        self,
        merge_service: JournalMergeService,
        journal_repo: SqlJournalRepository,
        gear_usage_repo: SqlGearUsageDataRepository,
        gear: list[UUID],
        clean_database: AsyncConnection,
    ) -> None:
        rope, harness, helmet = gear
        target_id = await self._journal(journal_repo, "Trip")
        source_id = await self._journal(journal_repo, "Trip (import)")
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=target_id,
                items=(
                    GearUsageItem(gear_item_id=rope),
                    GearUsageItem(gear_item_id=harness),
                ),
            )
        )
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=source_id,
                items=(
                    GearUsageItem(gear_item_id=harness, checkin_date=_CHECKIN),
                    GearUsageItem(gear_item_id=helmet, checkin_date=_CHECKIN),
                ),
            )
        )

        await merge_service.merge_journals(target_id, source_id, clean_database)

        merged = await gear_usage_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert [(i.gear_item_id, i.checkin_date) for i in merged.items] == [
            (rope, None),
            (harness, None),
            (helmet, _CHECKIN),
        ]
        assert await gear_usage_repo.find_by_journal_id(source_id) is None

    async def test_a_source_only_entry_moves_with_its_items(
        self,
        merge_service: JournalMergeService,
        journal_repo: SqlJournalRepository,
        gear_usage_repo: SqlGearUsageDataRepository,
        gear: list[UUID],
        clean_database: AsyncConnection,
    ) -> None:
        rope, harness, _ = gear
        target_id = await self._journal(journal_repo, "Trip")
        source_id = await self._journal(journal_repo, "Gear for the trip")
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=source_id,
                items=(
                    GearUsageItem(gear_item_id=rope),
                    GearUsageItem(gear_item_id=harness),
                ),
            )
        )

        await merge_service.merge_journals(target_id, source_id, clean_database)

        merged = await gear_usage_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert [i.gear_item_id for i in merged.items] == [rope, harness]
