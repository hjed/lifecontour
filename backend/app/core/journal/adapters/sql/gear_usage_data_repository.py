"""SQL implementation of the GearUsageDataRepository."""

from uuid import UUID

from core_shared.models.journals import GearUsageData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import GearUsageDataRepository


class SqlGearUsageDataRepository(GearUsageDataRepository):
    """SQL implementation of GearUsageDataRepository."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> GearUsageData | None:
        """Find gear usage data by journal ID."""
        query = text(
            """
            SELECT journal_id, gear_item_id, checkout_date, checkin_date, created_at, updated_at
            FROM journal_gear_usage_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return GearUsageData(
            journal_id=row.journal_id,
            gear_item_id=row.gear_item_id
            if isinstance(row.gear_item_id, UUID)
            else UUID(row.gear_item_id),
            checkout_date=row.checkout_date,
            checkin_date=row.checkin_date,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, data: GearUsageData) -> GearUsageData:
        """Save gear usage data (insert or update)."""
        query = text(
            """
            INSERT INTO journal_gear_usage_data (
                journal_id, gear_item_id, checkout_date, checkin_date, created_at, updated_at
            ) VALUES (
                :journal_id, :gear_item_id, :checkout_date, :checkin_date, COALESCE(:created_at, now()), COALESCE(:updated_at, now())
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                gear_item_id = EXCLUDED.gear_item_id,
                checkout_date = EXCLUDED.checkout_date,
                checkin_date = EXCLUDED.checkin_date,
                updated_at = now()
            RETURNING journal_id, gear_item_id, checkout_date, checkin_date, created_at, updated_at
            """
        )

        result = await self.connection.execute(
            query,
            {
                "journal_id": data.journal_id,
                "gear_item_id": str(data.gear_item_id),
                "checkout_date": data.checkout_date,
                "checkin_date": data.checkin_date,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save gear usage data")

        import dataclasses

        return dataclasses.replace(
            data,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def delete(self, journal_id: int) -> None:
        """Delete gear usage data by journal ID."""
        query = text(
            "DELETE FROM journal_gear_usage_data WHERE journal_id = :journal_id"
        )
        await self.connection.execute(query, {"journal_id": journal_id})
