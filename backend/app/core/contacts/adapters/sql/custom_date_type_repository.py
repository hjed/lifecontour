"""SQL repository for custom date types."""

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


class SqlCustomDateTypeRepository(CustomDateTypeRepository):
    """SQL Implementation of the CustomDateTypeRepository."""

    def __init__(self, connection: AsyncConnection):
        """Initialize with database connection."""
        self.connection = connection

    async def create(self, name: str) -> CustomDateType:
        """Create a new custom date type."""
        stmt = (
            insert(custom_date_types_table)
            .values(name=name)
            .returning(
                custom_date_types_table.c.id,
                custom_date_types_table.c.name,
                custom_date_types_table.c.created_at,
                custom_date_types_table.c.updated_at,
            )
        )
        try:
            result = await self.connection.execute(stmt)
            row = result.first()
            if not row:
                raise RuntimeError("Failed to create custom date type")
        except IntegrityError as e:
            if "unique" in str(e).lower() and "name" in str(e).lower():
                raise DuplicateCustomDateTypeNameError(name) from e
            raise

        return CustomDateType(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_by_id(self, type_id: int) -> CustomDateType | None:
        """Find a custom date type by ID."""
        stmt = select(custom_date_types_table).where(
            custom_date_types_table.c.id == type_id
        )
        result = await self.connection.execute(stmt)
        row = result.first()
        if not row:
            return None

        return CustomDateType(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_by_name(self, name: str) -> CustomDateType | None:
        """Find a custom date type by name."""
        stmt = select(custom_date_types_table).where(
            custom_date_types_table.c.name == name
        )
        result = await self.connection.execute(stmt)
        row = result.first()
        if not row:
            return None

        return CustomDateType(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_all(self) -> list[CustomDateType]:
        """Get all custom date types."""
        stmt = select(custom_date_types_table).order_by(custom_date_types_table.c.name)
        result = await self.connection.execute(stmt)

        return [
            CustomDateType(
                id=row.id,
                name=row.name,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result.all()
        ]

    async def delete(self, type_id: int) -> None:
        """Delete a custom date type."""
        stmt = delete(custom_date_types_table).where(
            custom_date_types_table.c.id == type_id
        )
        try:
            result = await self.connection.execute(stmt)
            if result.rowcount == 0:
                raise CustomDateTypeNotFoundError(type_id)
        except IntegrityError as e:
            if (
                "fk_contact_important_dates_custom_type" in str(e).lower()
                or "foreign key" in str(e).lower()
            ):
                raise CustomDateTypeInUseError(type_id) from e
            raise
