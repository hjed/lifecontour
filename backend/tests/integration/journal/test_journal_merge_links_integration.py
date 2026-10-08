"""Integration tests for fitness merge modes and integration-link handling.

Merging two fitness journals has two readings, and the merge mode picks between
them:

- ``REPLACE`` treats them as rival descriptions of one activity — the target's
  numbers stand and the source's integration links are dropped.
- ``ADDITIVE`` treats them as two parts of one outing — the metrics add up and
  every one of the source's ``sync_metadata`` links carries over, so both remote
  Strava activities stay linked to the survivor.

``sync_metadata`` has no ``ON DELETE CASCADE``, so these tests also pin down that
a merge never leaves a link row pointing at the deleted source.
"""

from datetime import datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    FitnessData,
    FitnessMergeMode,
    Journal,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
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


@pytest.mark.integration
class TestFitnessMergeModes:
    """Fitness metrics and integration links across the two merge modes."""

    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection):
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def fitness_repo(self, clean_database: AsyncConnection):
        return SqlFitnessDataRepository(clean_database)

    @pytest.fixture
    def sync_metadata_repo(self, clean_database: AsyncConnection):
        return SyncMetadataRepository(clean_database)

    @pytest.fixture
    def merge_service(self, journal_repo, clean_database: AsyncConnection):
        return JournalMergeService(
            journal_repo=journal_repo,
            event_publisher=OutboxEventPublisher(clean_database),
            task_merge_service=TaskJournalMergeService(
                task_anchor_repo=SqlTaskAnchorRepository(clean_database),
                event_publisher=OutboxEventPublisher(clean_database),
            ),
        )

    async def _create_journal(self, journal_repo, title: str) -> int:
        journal = await journal_repo.save(
            Journal(
                id=None,
                user_id=USER_ID,
                title=title,
                content="",
                event_date_range=EventDateRange(
                    start=datetime(2026, 3, 20, 8, 0),
                    end=datetime(2026, 3, 20, 9, 0),
                ),
            )
        )
        journal_id: int | None = journal.id
        assert journal_id is not None
        return journal_id

    async def _link_strava_activity(
        self, sync_metadata_repo, journal_id: int, activity_id: str
    ) -> None:
        await sync_metadata_repo.upsert(
            user_id=USER_ID,
            integration_source="strava",
            external_id=activity_id,
            version_hash=f"hash-{activity_id}",
            internal_id=journal_id,
            internal_entity_type="journal",
            external_entity_type="activity",
        )

    async def _strava_links(
        self, connection: AsyncConnection, journal_id: int
    ) -> list[str]:
        result = await connection.execute(
            text(
                """
                SELECT external_id
                FROM sync_metadata
                WHERE internal_entity_type = 'journal'
                  AND integration_source = 'strava'
                  AND internal_id = :journal_id
                ORDER BY external_id
                """
            ),
            {"journal_id": journal_id},
        )
        return [row.external_id for row in result.fetchall()]

    @pytest.mark.asyncio
    async def test_additive_merge_sums_metrics_and_keeps_both_strava_links(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        target_id = await self._create_journal(journal_repo, "Ride part 1")
        source_id = await self._create_journal(journal_repo, "Ride part 2")

        await fitness_repo.save(
            FitnessData(
                journal_id=target_id,
                distance=5000,
                duration=1800,
                elevation_gain=50,
                calories=300,
                heart_rate_avg=140,
                heart_rate_max=175,
                strava_activity_id="111",
            )
        )
        await fitness_repo.save(
            FitnessData(
                journal_id=source_id,
                distance=3000,
                duration=1200,
                elevation_gain=30,
                calories=200,
                heart_rate_avg=160,
                heart_rate_max=185,
                strava_activity_id="222",
            )
        )
        await self._link_strava_activity(sync_metadata_repo, target_id, "111")
        await self._link_strava_activity(sync_metadata_repo, source_id, "222")

        await merge_service.merge_journals(
            target_id,
            source_id,
            clean_database,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        merged = await fitness_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert merged.distance == 8000
        assert merged.duration == 3000
        assert merged.elevation_gain == 80
        assert merged.calories == 500
        assert merged.heart_rate_avg == 148  # duration-weighted
        assert merged.heart_rate_max == 185
        assert merged.strava_activity_id == "111"

        # Both remote activities remain linked to the survivor.
        assert await self._strava_links(clean_database, target_id) == ["111", "222"]
        assert await self._strava_links(clean_database, source_id) == []

        assert await fitness_repo.find_by_journal_id(source_id) is None
        assert await journal_repo.find_by_id(source_id) is None

    @pytest.mark.asyncio
    async def test_replace_merge_keeps_target_metrics_and_drops_the_source_link(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        target_id = await self._create_journal(journal_repo, "Ride")
        source_id = await self._create_journal(journal_repo, "Ride re-import")

        await fitness_repo.save(
            FitnessData(
                journal_id=target_id,
                distance=5000,
                duration=1800,
                strava_activity_id="111",
            )
        )
        await fitness_repo.save(
            FitnessData(
                journal_id=source_id,
                distance=3000,
                duration=1200,
                calories=200,
                strava_activity_id="222",
            )
        )
        await self._link_strava_activity(sync_metadata_repo, target_id, "111")
        await self._link_strava_activity(sync_metadata_repo, source_id, "222")

        await merge_service.merge_journals(target_id, source_id, clean_database)

        merged = await fitness_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert merged.distance == 5000
        assert merged.duration == 1800
        assert merged.calories == 200  # gaps still fill from the source

        # The losing link is removed rather than left pointing at a deleted journal.
        assert await self._strava_links(clean_database, target_id) == ["111"]
        orphans = await clean_database.execute(
            text(
                """
                SELECT count(*) AS n
                FROM sync_metadata
                WHERE internal_entity_type = 'journal' AND internal_id = :source_id
                """
            ),
            {"source_id": source_id},
        )
        orphan_row = orphans.fetchone()
        assert orphan_row is not None
        assert orphan_row.n == 0

    @pytest.mark.asyncio
    async def test_replace_merge_carries_over_a_link_the_target_lacks(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        """A service the target has no link for is re-pointed, not discarded."""
        target_id = await self._create_journal(journal_repo, "Bushwalk")
        source_id = await self._create_journal(journal_repo, "Bushwalk photos")

        await self._link_strava_activity(sync_metadata_repo, target_id, "111")
        await sync_metadata_repo.upsert(
            user_id=USER_ID,
            integration_source="immich",
            external_id="album-abc",
            version_hash="hash-album",
            internal_id=source_id,
            internal_entity_type="journal",
            external_entity_type="album",
        )

        await merge_service.merge_journals(target_id, source_id, clean_database)

        result = await clean_database.execute(
            text(
                """
                SELECT integration_source, external_id
                FROM sync_metadata
                WHERE internal_entity_type = 'journal' AND internal_id = :journal_id
                ORDER BY integration_source
                """
            ),
            {"journal_id": target_id},
        )
        assert [
            (row.integration_source, row.external_id) for row in result.fetchall()
        ] == [
            ("immich", "album-abc"),
            ("strava", "111"),
        ]

    @pytest.mark.asyncio
    async def test_replace_merge_drops_the_source_link_against_a_hand_typed_id(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        """A Strava id typed into the fitness editor still counts as the target's link.

        It has no ``sync_metadata`` row behind it, so without folding the
        fitness column in, the source's Strava link looks like a service the
        target does not use and gets carried over — leaving the survivor linked
        to both activities in the mode meant to keep one.
        """
        target_id = await self._create_journal(journal_repo, "Ride")
        source_id = await self._create_journal(journal_repo, "Ride re-import")

        # The target's link exists only as a hand-entered id.
        await fitness_repo.save(
            FitnessData(journal_id=target_id, distance=5000, strava_activity_id="111")
        )
        await fitness_repo.save(
            FitnessData(journal_id=source_id, distance=3000, strava_activity_id="222")
        )
        await self._link_strava_activity(sync_metadata_repo, source_id, "222")

        await merge_service.merge_journals(target_id, source_id, clean_database)

        assert await self._strava_links(clean_database, target_id) == []
        assert await self._strava_links(clean_database, source_id) == []

    @pytest.mark.asyncio
    async def test_additive_merge_keeps_a_hand_typed_source_activity_linked(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        """The source's fitness row is deleted by the merge, so its id must move.

        With no sync row behind a hand-entered id and the survivor keeping its
        own, the source's activity would otherwise vanish entirely.
        """
        target_id = await self._create_journal(journal_repo, "Ride part 1")
        source_id = await self._create_journal(journal_repo, "Ride part 2")

        await fitness_repo.save(
            FitnessData(journal_id=target_id, distance=5000, strava_activity_id="111")
        )
        await fitness_repo.save(
            FitnessData(journal_id=source_id, distance=3000, strava_activity_id="222")
        )
        await self._link_strava_activity(sync_metadata_repo, target_id, "111")

        await merge_service.merge_journals(
            target_id,
            source_id,
            clean_database,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        assert await self._strava_links(clean_database, target_id) == ["111", "222"]
        # The link the merge creates for the hand-typed id is the journal owner's.
        owner = (
            await clean_database.execute(
                text(
                    "SELECT user_id FROM sync_metadata "
                    "WHERE integration_source = 'strava' AND external_id = '222'"
                )
            )
        ).scalar_one()
        assert owner == USER_ID

    @pytest.mark.asyncio
    async def test_merge_does_not_treat_the_same_activity_as_a_collision(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        sync_metadata_repo,
        clean_database: AsyncConnection,
    ):
        """Both journals naming one activity leaves it linked, in either mode."""
        target_id = await self._create_journal(journal_repo, "Ride")
        source_id = await self._create_journal(journal_repo, "Ride duplicate")

        await fitness_repo.save(
            FitnessData(journal_id=target_id, distance=5000, strava_activity_id="111")
        )
        await self._link_strava_activity(sync_metadata_repo, source_id, "111")

        await merge_service.merge_journals(target_id, source_id, clean_database)

        assert await self._strava_links(clean_database, target_id) == ["111"]

    @pytest.mark.asyncio
    async def test_additive_merge_moves_a_source_only_fitness_row(
        self,
        merge_service,
        journal_repo,
        fitness_repo,
        clean_database: AsyncConnection,
    ):
        """With nothing to add to, the source's row simply becomes the target's."""
        target_id = await self._create_journal(journal_repo, "Saturday outing")
        source_id = await self._create_journal(journal_repo, "Saturday ride")

        await fitness_repo.save(
            FitnessData(journal_id=source_id, distance=3000, duration=1200)
        )

        await merge_service.merge_journals(
            target_id,
            source_id,
            clean_database,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        merged = await fitness_repo.find_by_journal_id(target_id)
        assert merged is not None
        assert merged.distance == 3000
        assert merged.duration == 1200
