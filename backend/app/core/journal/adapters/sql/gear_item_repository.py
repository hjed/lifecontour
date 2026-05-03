"""SQL implementation of GearItemRepository."""

from datetime import date
from typing import Any

from core_shared.models.journals import GearItem
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import GearItemRepository


class SqlGearItemRepository(GearItemRepository):
    """SQL implementation of GearItemRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> GearItem:
        """Convert a database row to a GearItem entity."""
        purchase_date = row.purchase_date
        if purchase_date is not None and not isinstance(purchase_date, date):
            purchase_date = date.fromisoformat(str(purchase_date))

        return GearItem(
            id=str(row.id),
            user_id=row.user_id,
            name=row.name,
            model=row.model,
            serial_number=row.serial_number,
            purchase_date=purchase_date,
            manufacturer=row.manufacturer,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, gear_item: GearItem) -> GearItem:
        """Save a gear item (upsert based on id)."""
        query = text(
            """
            INSERT INTO gear_items (
                id, user_id, name, model, serial_number,
                purchase_date, manufacturer
            )
            VALUES (
                :id, :user_id, :name, :model, :serial_number,
                :purchase_date, :manufacturer
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                model = EXCLUDED.model,
                serial_number = EXCLUDED.serial_number,
                purchase_date = EXCLUDED.purchase_date,
                manufacturer = EXCLUDED.manufacturer,
                updated_at = now()
            RETURNING id, user_id, name, model, serial_number,
                      purchase_date, manufacturer, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "id": gear_item.id,
                "user_id": gear_item.user_id,
                "name": gear_item.name,
                "model": gear_item.model,
                "serial_number": gear_item.serial_number,
                "purchase_date": gear_item.purchase_date,
                "manufacturer": gear_item.manufacturer,
            },
        )
        row = result.fetchone()

        if not row:
            raise ValueError("Failed to save gear item")

        return self._row_to_entity(row)

    async def find_by_id(self, gear_item_id: str) -> GearItem | None:
        """Find a gear item by ID."""
        query = text(
            """
            SELECT id, user_id, name, model, serial_number,
                   purchase_date, manufacturer, created_at, updated_at
            FROM gear_items
            WHERE id = :id
            """
        )
        result = await self.conn.execute(query, {"id": gear_item_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_entity(row)

    async def find_by_user(self, user_id: str) -> list[GearItem]:
        """Find all gear items for a user, ordered by name."""
        query = text(
            """
            SELECT id, user_id, name, model, serial_number,
                   purchase_date, manufacturer, created_at, updated_at
            FROM gear_items
            WHERE user_id = :user_id
            ORDER BY name ASC
            """
        )
        result = await self.conn.execute(query, {"user_id": user_id})
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def search_by_name(self, user_id: str, query: str) -> list[GearItem]:
        """Search gear items by name using case-insensitive partial matching."""
        sql = text(
            """
            SELECT id, user_id, name, model, serial_number,
                   purchase_date, manufacturer, created_at, updated_at
            FROM gear_items
            WHERE user_id = :user_id
              AND name ILIKE :query
            ORDER BY name ASC
            """
        )
        result = await self.conn.execute(
            sql,
            {
                "user_id": user_id,
                "query": f"%{query}%",
            },
        )
        rows = result.fetchall()

        return [self._row_to_entity(row) for row in rows]

    async def delete(self, gear_item_id: str) -> None:
        """Delete a gear item by ID."""
        query = text("DELETE FROM gear_items WHERE id = :id")
        await self.conn.execute(query, {"id": gear_item_id})
