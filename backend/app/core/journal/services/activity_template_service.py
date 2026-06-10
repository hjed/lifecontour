"""Service layer for activity template mutations.

Wraps activity template create/update/delete in explicit units of work so each
write is committed before the HTTP response is sent (issue #945), keeping
transaction ownership in the service layer rather than the controller.
"""

from core_shared.models.journals.activity_template import ActivityTemplate
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import ActivityTemplateRepository
from app.infrastructure.unit_of_work import transactional


class ActivityTemplateService:
    """Service for persisting activity templates as committed units of work."""

    def __init__(self, activity_template_repo: ActivityTemplateRepository) -> None:
        self.activity_template_repo = activity_template_repo

    @transactional
    async def create(
        self,
        template: ActivityTemplate,
        transaction: AsyncConnection,
    ) -> ActivityTemplate:
        """Persist a new activity template and return it as a committed unit.

        The caller is responsible for constructing and validating the entity.
        """
        return await self.activity_template_repo.save(template)

    @transactional
    async def update(
        self,
        template: ActivityTemplate,
        transaction: AsyncConnection,
    ) -> ActivityTemplate:
        """Persist changes to an activity template as a committed unit.

        The caller loads the template, applies the requested changes, and runs
        domain validation before calling this method.
        """
        return await self.activity_template_repo.save(template)

    @transactional
    async def delete(
        self,
        template_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Delete an activity template as a committed unit.

        The caller is responsible for verifying existence and ownership.
        """
        await self.activity_template_repo.delete(template_id)
