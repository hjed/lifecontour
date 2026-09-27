"""Merging journals keeps every gear item either of them recorded.

A GEAR_USAGE entry holds a list of gear items. When both journals have one, the
target keeps its items and gains the source's; a gear item both list takes its
dates by the rule every merged field follows. When only the source has one, the
entry moves across with its items. The source's Snipe-IT pairs move with them.
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
from sqlalchemy import text
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
_EARLIER = datetime(2026, 3, 19, 18, 0, tzinfo=UTC)
_BEFORE_CHECKOUT = datetime(2026, 3, 19, 20, 0, tzinfo=UTC)
_CHECKOUT = datetime(2026, 3, 20, 7, 0, tzinfo=UTC)
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
            # Listed by both; only the source dated it, so its dates are kept.
            (harness, _CHECKIN),
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

    async def test_a_shared_gear_item_takes_the_dates_only_the_source_has(
        self,
        merge_service: JournalMergeService,
        journal_repo: SqlJournalRepository,
        gear_usage_repo: SqlGearUsageDataRepository,
        gear: list[UUID],
        clean_database: AsyncConnection,
    ) -> None:
        """Like any merged field, a value only the source holds is kept."""
        rope = gear[0]
        target_id = await self._journal(journal_repo, "Trip")
        source_id = await self._journal(journal_repo, "Trip (import)")
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=target_id, items=(GearUsageItem(gear_item_id=rope),)
            )
        )
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=source_id,
                items=(GearUsageItem(gear_item_id=rope, checkin_date=_CHECKIN),),
            )
        )

        await merge_service.merge_journals(target_id, source_id, clean_database)

        merged = await gear_usage_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert [(i.gear_item_id, i.checkin_date) for i in merged.items] == [
            (rope, _CHECKIN)
        ]

    @pytest.mark.parametrize(
        ("source_wins", "target_dates", "source_dates", "merged_dates"),
        [
            # Each date is merged on its own, as every merged field is: the
            # source's fills a date the target lacks...
            (False, (_CHECKOUT, None), (None, _CHECKIN), (_CHECKOUT, _CHECKIN)),
            # ...and, when the source survives, a date the source holds wins,
            # but its missing one never erases the target's.
            (True, (_CHECKOUT, None), (None, _CHECKIN), (_CHECKOUT, _CHECKIN)),
            (True, (_CHECKOUT, _CHECKIN), (_EARLIER, None), (_EARLIER, _CHECKIN)),
            (False, (_CHECKOUT, _CHECKIN), (_EARLIER, None), (_CHECKOUT, _CHECKIN)),
            # A window stitched from both sides that would end before it starts
            # falls back to the winning side's own window.
            (True, (None, _BEFORE_CHECKOUT), (_CHECKOUT, None), (_CHECKOUT, None)),
            (
                False,
                (None, _BEFORE_CHECKOUT),
                (_CHECKOUT, None),
                (None, _BEFORE_CHECKOUT),
            ),
        ],
    )
    async def test_a_shared_gear_items_dates_merge_field_by_field(
        self,
        journal_repo: SqlJournalRepository,
        gear_usage_repo: SqlGearUsageDataRepository,
        gear: list[UUID],
        clean_database: AsyncConnection,
        source_wins: bool,
        target_dates: tuple[datetime | None, datetime | None],
        source_dates: tuple[datetime | None, datetime | None],
        merged_dates: tuple[datetime | None, datetime | None],
    ) -> None:
        rope = gear[0]
        ids = []
        for title, (checkout, checkin) in (
            ("Trip", target_dates),
            ("Trip (import)", source_dates),
        ):
            journal_id = await self._journal(journal_repo, title)
            await gear_usage_repo.save(
                GearUsageData(
                    journal_id=journal_id,
                    items=(
                        GearUsageItem(
                            gear_item_id=rope,
                            checkout_date=checkout,
                            checkin_date=checkin,
                        ),
                    ),
                )
            )
            ids.append(journal_id)
        target_id, source_id = ids

        await JournalMergeService._merge_gear_usage_items(
            target_id,
            source_id,
            source_wins=source_wins,
            changed_fields={},
            transaction=clean_database,
        )

        merged = await gear_usage_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert [(i.checkout_date, i.checkin_date) for i in merged.items] == [
            merged_dates
        ]

    async def test_the_sources_snipeit_pairs_move_to_the_target(
        self,
        merge_service: JournalMergeService,
        journal_repo: SqlJournalRepository,
        gear_usage_repo: SqlGearUsageDataRepository,
        gear: list[UUID],
        clean_database: AsyncConnection,
    ) -> None:
        """The merged journal keeps the Snipe-IT history of the gear it gained.

        Left keyed to the deleted source, the source's checkout would be checked
        in by the deletion while the trip still lists the gear.
        """
        rope, harness, _ = gear
        target_id = await self._journal(journal_repo, "Trip")
        source_id = await self._journal(journal_repo, "Gear for the trip")
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=target_id, items=(GearUsageItem(gear_item_id=rope),)
            )
        )
        await gear_usage_repo.save(
            GearUsageData(
                journal_id=source_id,
                items=(
                    GearUsageItem(gear_item_id=rope),
                    GearUsageItem(gear_item_id=harness),
                ),
            )
        )
        # Asset 41 is the rope, which both journals checked out; 42 the harness.
        for journal_id, source, asset in (
            (target_id, "snipeit_checkout", 41),
            (source_id, "snipeit_checkout", 41),
            (source_id, "snipeit_checkin", 41),
            (source_id, "snipeit_checkout", 42),
            (source_id, "snipeit_checkin", 42),
        ):
            await clean_database.execute(
                text(
                    """
                    INSERT INTO sync_metadata
                        (internal_uuid, integration_source, external_id,
                         last_synced_at, version_hash, sync_status, retry_count,
                         created_at, updated_at)
                    VALUES (:journal, :source, :external_id, now(), 'hash',
                            'success', 0, now(), now())
                    """
                ),
                {
                    "journal": str(journal_id),
                    "source": source,
                    "external_id": f"{source}:{asset}:{journal_id}",
                },
            )

        await merge_service.merge_journals(target_id, source_id, clean_database)

        rows = await clean_database.execute(
            text(
                """
                SELECT internal_uuid, external_id FROM sync_metadata
                WHERE integration_source IN ('snipeit_checkout', 'snipeit_checkin')
                ORDER BY external_id
                """
            )
        )
        assert sorted((r.internal_uuid, r.external_id) for r in rows) == sorted(
            [
                (str(target_id), f"snipeit_checkout:41:{target_id}"),
                # The target already has the rope's pair, so the source's pair
                # — checkout and check-in together — stays with the source.
                (str(source_id), f"snipeit_checkout:41:{source_id}"),
                (str(source_id), f"snipeit_checkin:41:{source_id}"),
                (str(target_id), f"snipeit_checkout:42:{target_id}"),
                (str(target_id), f"snipeit_checkin:42:{target_id}"),
            ]
        )
