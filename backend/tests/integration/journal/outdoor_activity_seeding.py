"""Shared seeding helpers for outdoor-activity integration tests.

Seeds journals with outdoor subtype data through the real repositories so
tests stay deterministic. ``USER_ID`` matches the ``authenticated_client`` /
MCP test session user, so seeded rows are visible to the app under test.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from core_shared.models.journals import (
    AbseilingData,
    ActivityTemplate,
    BushwalkingData,
    CanyoningData,
    EventDateRange,
    GearItem,
    GearUsageData,
    JoggingData,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    OutdoorActivityData,
    OutdoorPlanningData,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.gear_item_repository import (
    SqlGearItemRepository,
)
from app.core.journal.adapters.sql.gear_usage_data_repository import (
    SqlGearUsageDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.outdoor_planning_data_repository import (
    SqlOutdoorPlanningDataRepository,
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

    async def create_journal(
        self,
        *,
        title: str = "Journal",
        user_id: str = USER_ID,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """A bare journals row with no type data (defaults to a 1-hour range)."""
        start = start if start is not None else datetime.now(UTC)
        journal = await self.journal_repo.save(
            Journal(
                user_id=user_id,
                title=title,
                content="content",
                event_date_range=EventDateRange(
                    start=start,
                    end=end if end is not None else start + timedelta(hours=1),
                ),
            )
        )
        assert journal.id is not None
        return journal.id

    async def create_outdoor_journal(
        self,
        *,
        title: str = "Outdoor trip",
        user_id: str = USER_ID,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """An outdoor journal (journals row + outdoor_activity_data row)."""
        journal_id = await self.create_journal(
            title=title, user_id=user_id, start=start, end=end
        )
        await self.outdoor_activity_repo.save(
            OutdoorActivityData(journal_id=journal_id)
        )
        return journal_id

    async def create_outdoor_planning_journal(
        self,
        *,
        title: str = "Planning night",
        user_id: str = USER_ID,
        start: datetime | None = None,
    ) -> int:
        """An OUTDOOR_PLANNING journal (no outdoor_activity_data row)."""
        journal_id = await self.create_journal(
            title=title, user_id=user_id, start=start
        )
        await SqlOutdoorPlanningDataRepository(self.connection).save(
            OutdoorPlanningData(journal_id=journal_id)
        )
        return journal_id

    async def create_jogging_journal(
        self,
        *,
        title: str = "Morning jog",
        user_id: str = USER_ID,
        start: datetime | None = None,
    ) -> int:
        """A jogging journal — fitness-only, not an outdoor activity."""
        journal_id = await self.create_journal(
            title=title, user_id=user_id, start=start
        )
        await SqlJoggingDataRepository(self.connection).save(
            JoggingData(journal_id=journal_id)
        )
        return journal_id

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

    async def create_gear_item(
        self, *, name: str = "Test Rope", user_id: str = USER_ID
    ) -> str:
        """A user-owned gear item; returns its UUID string."""
        gear_item = await SqlGearItemRepository(self.connection).save(
            GearItem(name=name, user_id=user_id)
        )
        assert gear_item.id is not None
        return gear_item.id

    async def create_gear_usage_journal(
        self,
        gear_item_id: str,
        *,
        title: str = "Gear usage",
        user_id: str = USER_ID,
        start: datetime | None = None,
        end: datetime | None = None,
        checkout_date: datetime | None = None,
        checkin_date: datetime | None = None,
    ) -> int:
        """A GEAR_USAGE journal referencing ``gear_item_id``.

        ``checkout_date``/``checkin_date`` are the optional buffer overrides;
        when unset the checkout window resolves to the journal's event range.
        """
        journal_id = await self.create_journal(
            title=title, user_id=user_id, start=start, end=end
        )
        await SqlGearUsageDataRepository(self.connection).save(
            GearUsageData(
                journal_id=journal_id,
                gear_item_id=UUID(gear_item_id),
                checkout_date=checkout_date,
                checkin_date=checkin_date,
            )
        )
        return journal_id

    async def insert_snipeit_checkin(
        self, journal_id: int, *, sync_status: str = "success"
    ) -> None:
        """A ``snipeit_checkin`` sync row, as the worker records a return."""
        await self.connection.execute(
            text(
                """
                INSERT INTO sync_metadata
                    (internal_uuid, integration_source, external_id,
                     last_synced_at, version_hash, sync_status, retry_count,
                     created_at, updated_at)
                VALUES
                    (:journal_id, 'snipeit_checkin', :external_id, now(),
                     'CHECKED_IN', :sync_status, 0, now(), now())
                """
            ),
            {
                "journal_id": str(journal_id),
                "external_id": f"snipeit_checkin:{journal_id}",
                "sync_status": sync_status,
            },
        )

    async def create_template(
        self,
        *,
        name: str = "Empress Falls",
        template_type: str = "canyoning",
        user_id: str = USER_ID,
    ) -> str:
        """A user-owned activity template; returns its UUID string."""
        template = await SqlActivityTemplateRepository(self.connection).save(
            ActivityTemplate(name=name, template_type=template_type, user_id=user_id)
        )
        assert template.id is not None
        return template.id

    async def create_abseiling_journal(
        self,
        *,
        title: str = "Abseil day",
        user_id: str = USER_ID,
        start: datetime | None = None,
        template_id: str | None = None,
    ) -> int:
        """An abseiling outdoor journal, optionally referencing a template."""
        journal_id = await self.create_outdoor_journal(
            title=title, user_id=user_id, start=start
        )
        await SqlAbseilingDataRepository(self.connection).save(
            AbseilingData(journal_id=journal_id, template_id=template_id)
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
