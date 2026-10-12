"""SQL repository for custom date types."""

from typing import Any

from core_shared.models.contacts.important_date_types import CustomDateType
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    CustomDateTypeInUseError,
    CustomDateTypeNotFoundError,
    DuplicateCustomDateTypeNameError,
)
from app.core.contacts.models.repositories import CustomDateTypeRepository
from app.infrastructure.contacts.contact_tables import custom_date_types_table

# Named by migrations 0134 and 0044 (the latter left the FK to PostgreSQL's
# default name), so the errors map on the constraint rather than on wording.
_PER_USER_NAME_KEY = "uq_custom_date_types_user_id_name"
_DATES_FOREIGN_KEY = "contact_important_dates_custom_date_type_id_fkey"


def _to_entity(row: Any) -> CustomDateType:
    """Map a ``custom_date_types`` row, owner included, to the entity."""
    return CustomDateType(
        id=row.id,
        name=row.name,
        user_id=row.user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlCustomDateTypeRepository(CustomDateTypeRepository):
    """SQL Implementation of the CustomDateTypeRepository."""

    def __init__(self, connection: AsyncConnection):
        """Initialize with database connection."""
        self.connection = connection

    async def create(self, name: str, *, user_id: str) -> CustomDateType:
        """Create a new custom date type owned by ``user_id``."""
        stmt = (
            insert(custom_date_types_table)
            .values(name=name, user_id=user_id)
            .returning(*custom_date_types_table.c)
        )
        try:
            result = await self.connection.execute(stmt)
            row = result.first()
            if not row:
                raise RuntimeError("Failed to create custom date type")
        except IntegrityError as e:
            if _PER_USER_NAME_KEY in str(e):
                raise DuplicateCustomDateTypeNameError(name) from e
            raise

        return _to_entity(row)

    async def get_by_id(self, type_id: int, *, user_id: str) -> CustomDateType | None:
        """Find ``user_id``'s custom date type by ID; another user's reads as missing."""
        stmt = select(custom_date_types_table).where(
            custom_date_types_table.c.id == type_id,
            custom_date_types_table.c.user_id == user_id,
        )
        row = (await self.connection.execute(stmt)).first()
        return _to_entity(row) if row else None

    async def get_by_name(self, name: str, *, user_id: str) -> CustomDateType | None:
        """Find ``user_id``'s custom date type by name."""
        stmt = select(custom_date_types_table).where(
            custom_date_types_table.c.name == name,
            custom_date_types_table.c.user_id == user_id,
        )
        row = (await self.connection.execute(stmt)).first()
        return _to_entity(row) if row else None

    async def list_all(self, *, user_id: str) -> list[CustomDateType]:
        """Get every custom date type ``user_id`` owns, by name."""
        stmt = (
            select(custom_date_types_table)
            .where(custom_date_types_table.c.user_id == user_id)
            .order_by(custom_date_types_table.c.name)
        )
        result = await self.connection.execute(stmt)

        return [_to_entity(row) for row in result.all()]

    async def delete(self, type_id: int, *, user_id: str) -> None:
        """Delete ``user_id``'s custom date type; another user's is not found."""
        stmt = delete(custom_date_types_table).where(
            custom_date_types_table.c.id == type_id,
            custom_date_types_table.c.user_id == user_id,
        )
        try:
            result = await self.connection.execute(stmt)
        except IntegrityError as e:
            if _DATES_FOREIGN_KEY in str(e):
                raise CustomDateTypeInUseError(type_id) from e
            raise
        if result.rowcount == 0:
            raise CustomDateTypeNotFoundError(type_id)
