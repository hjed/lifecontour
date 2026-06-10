"""Service layer for custom date type mutations.

Wraps custom date type create/delete in explicit units of work so each write is
committed before the HTTP response is sent (issue #945), keeping transaction
ownership in the service layer rather than the controller.
"""

from core_shared.models.contacts.important_date_types import CustomDateType
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import CustomDateTypeRepository
from app.infrastructure.unit_of_work import transactional


class CustomDateTypeService:
    """Service for persisting custom date types as committed units of work."""

    def __init__(self, custom_date_type_repo: CustomDateTypeRepository) -> None:
        self.custom_date_type_repo = custom_date_type_repo

    @transactional
    async def create(
        self,
        name: str,
        transaction: AsyncConnection,
    ) -> CustomDateType:
        """Create a new custom date type and return it as a committed unit."""
        return await self.custom_date_type_repo.create(name)

    @transactional
    async def delete(
        self,
        type_id: int,
        transaction: AsyncConnection,
    ) -> None:
        """Delete a custom date type as a committed unit."""
        await self.custom_date_type_repo.delete(type_id)
