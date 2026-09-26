"""SQL implementation of the GearUsageDataRepository.

A journal's GEAR_USAGE entry is its ``journal_gear_usage_data`` row; the gear
items it holds are ``journal_gear_usage_items`` rows, in ``position`` order.

Until the legacy columns are dropped, the entry's own ``gear_item_id`` /
``checkout_date`` / ``checkin_date`` mirror its first item (NULL when it has
none), so readers not yet moved to the items table keep seeing what they did
when an entry held a single item.
"""

from uuid import UUID

from core_shared.models.journals import GearUsageData, GearUsageItem
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import GearUsageDataRepository


def _as_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class SqlGearUsageDataRepository(GearUsageDataRepository):
    """SQL implementation of GearUsageDataRepository."""

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> GearUsageData | None:
        """Find a journal's gear usage entry and its items."""
        entry = (
            await self.connection.execute(
                text(
                    """
                    SELECT journal_id, created_at, updated_at
                    FROM journal_gear_usage_data
                    WHERE journal_id = :journal_id
                    """
                ),
                {"journal_id": journal_id},
            )
        ).fetchone()
        if not entry:
            return None

        items = (
            await self.connection.execute(
                text(
                    """
                    SELECT gear_item_id, checkout_date, checkin_date,
                           created_at, updated_at
                    FROM journal_gear_usage_items
                    WHERE journal_id = :journal_id
                    ORDER BY position, gear_item_id
                    """
                ),
                {"journal_id": journal_id},
            )
        ).fetchall()

        return GearUsageData(
            journal_id=entry.journal_id,
            items=tuple(
                GearUsageItem(
                    gear_item_id=_as_uuid(row.gear_item_id),
                    checkout_date=row.checkout_date,
                    checkin_date=row.checkin_date,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in items
            ),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    async def save(self, data: GearUsageData) -> GearUsageData:
        """Save the entry with exactly ``data``'s items, in their order.

        Items no longer listed are removed; listed ones are inserted or have
        their dates and position updated, keeping ``created_at``.
        """
        if data.journal_id is None:
            raise ValueError("GearUsageData.journal_id is required to save")
        journal_id = data.journal_id

        await self.connection.execute(
            text(
                """
                INSERT INTO journal_gear_usage_data (journal_id)
                VALUES (:journal_id)
                ON CONFLICT (journal_id) DO UPDATE SET updated_at = now()
                """
            ),
            {"journal_id": journal_id},
        )

        await self.connection.execute(
            text(
                """
                DELETE FROM journal_gear_usage_items
                WHERE journal_id = :journal_id
                  AND NOT (gear_item_id = ANY(CAST(:kept AS uuid[])))
                """
            ),
            {
                "journal_id": journal_id,
                "kept": [str(item.gear_item_id) for item in data.items],
            },
        )

        for position, item in enumerate(data.items):
            await self.connection.execute(
                text(
                    """
                    INSERT INTO journal_gear_usage_items (
                        journal_id, gear_item_id, position,
                        checkout_date, checkin_date
                    ) VALUES (
                        :journal_id, :gear_item_id, :position,
                        :checkout_date, :checkin_date
                    )
                    ON CONFLICT (journal_id, gear_item_id) DO UPDATE SET
                        position = EXCLUDED.position,
                        checkout_date = EXCLUDED.checkout_date,
                        checkin_date = EXCLUDED.checkin_date,
                        updated_at = now()
                    WHERE (
                        journal_gear_usage_items.position,
                        journal_gear_usage_items.checkout_date,
                        journal_gear_usage_items.checkin_date
                    ) IS DISTINCT FROM (
                        EXCLUDED.position,
                        EXCLUDED.checkout_date,
                        EXCLUDED.checkin_date
                    )
                    """
                ),
                {
                    "journal_id": journal_id,
                    "gear_item_id": str(item.gear_item_id),
                    "position": position,
                    "checkout_date": item.checkout_date,
                    "checkin_date": item.checkin_date,
                },
            )

        await self._refresh_mirror(journal_id)

        saved = await self.find_by_journal_id(journal_id)
        if saved is None:
            raise RuntimeError("Failed to save gear usage data")
        return saved

    async def _refresh_mirror(self, journal_id: int) -> None:
        """Copy the entry's first item into its legacy single-item columns."""
        await self.connection.execute(
            text(
                """
                UPDATE journal_gear_usage_data d
                SET gear_item_id = first_item.gear_item_id,
                    checkout_date = first_item.checkout_date,
                    checkin_date = first_item.checkin_date
                FROM (SELECT 1) AS one
                LEFT JOIN LATERAL (
                    SELECT gear_item_id, checkout_date, checkin_date
                    FROM journal_gear_usage_items
                    WHERE journal_id = :journal_id
                    ORDER BY position, gear_item_id
                    LIMIT 1
                ) first_item ON true
                WHERE d.journal_id = :journal_id
                """
            ),
            {"journal_id": journal_id},
        )

    async def delete(self, journal_id: int) -> None:
        """Delete a journal's gear usage entry; its items cascade with it."""
        query = text(
            "DELETE FROM journal_gear_usage_data WHERE journal_id = :journal_id"
        )
        await self.connection.execute(query, {"journal_id": journal_id})
