"""SQL implementation of the GearMaintenanceDataRepository."""

import json
from uuid import UUID

from core_shared.models.journals import GearMaintenanceData
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import GearMaintenanceDataRepository


class SqlGearMaintenanceDataRepository(GearMaintenanceDataRepository):
    """SQL implementation of GearMaintenanceDataRepository."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> GearMaintenanceData | None:
        """Find gear maintenance data by journal ID."""
        query = text(
            """
            SELECT journal_id, gear_item_id, maintenance_type, activity_types, retirement_reason, created_at, updated_at
            FROM journal_gear_maintenance_data
            WHERE journal_id = :journal_id
            """
        )
        result = await self.connection.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        # Handle JSONB parsing for activity_types
        activity_types = row.activity_types
        if isinstance(activity_types, str):
            activity_types = json.loads(activity_types)

        return GearMaintenanceData(
            journal_id=row.journal_id,
            gear_item_id=row.gear_item_id
            if isinstance(row.gear_item_id, UUID)
            else UUID(row.gear_item_id),
            maintenance_type=row.maintenance_type,
            activity_types=activity_types if activity_types else [],
            retirement_reason=row.retirement_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, data: GearMaintenanceData) -> GearMaintenanceData:
        """Save gear maintenance data (insert or update)."""
        # Convert list to JSON string if needed for SQLAlchemy parameterized queries
        activity_types_json = (
            json.dumps(data.activity_types) if data.activity_types else "[]"
        )

        query = text(
            """
            INSERT INTO journal_gear_maintenance_data (
                journal_id, gear_item_id, maintenance_type, activity_types, retirement_reason, created_at, updated_at
            ) VALUES (
                :journal_id, :gear_item_id, :maintenance_type, CAST(:activity_types AS jsonb), :retirement_reason, COALESCE(:created_at, now()), COALESCE(:updated_at, now())
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                gear_item_id = EXCLUDED.gear_item_id,
                maintenance_type = EXCLUDED.maintenance_type,
                activity_types = EXCLUDED.activity_types,
                retirement_reason = EXCLUDED.retirement_reason,
                updated_at = now()
            RETURNING journal_id, gear_item_id, maintenance_type, activity_types, retirement_reason, created_at, updated_at
            """
        )

        result = await self.connection.execute(
            query,
            {
                "journal_id": data.journal_id,
                "gear_item_id": str(data.gear_item_id),
                "maintenance_type": data.maintenance_type,
                "activity_types": activity_types_json,
                "retirement_reason": data.retirement_reason,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            },
        )
        row = result.fetchone()

        if not row:
            raise RuntimeError("Failed to save gear maintenance data")

        activity_types = row.activity_types
        if isinstance(activity_types, str):
            activity_types = json.loads(activity_types)

        import dataclasses

        return dataclasses.replace(
            data,
            created_at=row.created_at,
            updated_at=row.updated_at,
            activity_types=activity_types if activity_types else [],
        )

    async def delete(self, journal_id: int) -> None:
        """Delete gear maintenance data by journal ID."""
        query = text(
            "DELETE FROM journal_gear_maintenance_data WHERE journal_id = :journal_id"
        )
        await self.connection.execute(query, {"journal_id": journal_id})
