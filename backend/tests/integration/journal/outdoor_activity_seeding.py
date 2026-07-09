"""Shared seeding helpers for outdoor-activity integration tests.

Seeds journals with outdoor subtype data through the real repositories so
tests stay deterministic. ``USER_ID`` matches the ``authenticated_client`` /
MCP test session user, so seeded rows are visible to the app under test.
"""

from datetime import UTC, datetime, timedelta

from core_shared.models.journals import (
    AbseilingData,
    BushwalkingData,
    CanyoningData,
    EventDateRange,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    OutdoorActivityData,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)

USER_ID = "test-user-123"
OTHER_USER_ID = "test-user-456"


class Seeder:
    """Seeds journals with outdoor subtype data through the real repositories."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection
        self.journal_repo = SqlJournalRepository(connection)
        self.outdoor_activity_repo = SqlOutdoorActivityDataRepository(connection)
        self.relationship_repo = SqlJournalContactRelationshipRepository(connection)

    async def create_outdoor_journal(
        self,
        *,
        title: str = "Outdoor trip",
        user_id: str = USER_ID,
        start: datetime | None = None,
    ) -> int:
        """An outdoor journal (journals row + outdoor_activity_data row)."""
        start = start if start is not None else datetime.now(UTC)
        journal = await self.journal_repo.save(
            Journal(
                user_id=user_id,
                title=title,
                content="content",
                event_date_range=EventDateRange(
                    start=start, end=start + timedelta(hours=1)
                ),
            )
        )
        assert journal.id is not None
        await self.outdoor_activity_repo.save(
            OutdoorActivityData(journal_id=journal.id)
        )
        return journal.id

    async def create_incomplete_canyoning_journal(
        self,
        *,
        title: str = "Empty canyon",
        user_id: str = USER_ID,
        start: datetime | None = None,
    ) -> int:
        """An attribute-less canyoning journal matching all three rules.

        Seeds the dependency-added bushwalking/abseiling rows alongside the
        canyoning row, all attribute-less, with no template and no participants.
        """
        journal_id = await self.create_outdoor_journal(
            title=title, user_id=user_id, start=start
        )
        await SqlBushwalkingDataRepository(self.connection).save(
            BushwalkingData(journal_id=journal_id)
        )
        await SqlAbseilingDataRepository(self.connection).save(
            AbseilingData(journal_id=journal_id)
        )
        await SqlCanyoningDataRepository(self.connection).save(
            CanyoningData(journal_id=journal_id)
        )
        return journal_id

    async def add_participant(self, journal_id: int) -> None:
        contact_result = await self.connection.execute(
            text("INSERT INTO contacts (first_name) VALUES (:name) RETURNING id"),
            {"name": "Participant"},
        )
        contact_id = contact_result.scalar()
        assert contact_id is not None
        await self.relationship_repo.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=contact_id,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )
        )
