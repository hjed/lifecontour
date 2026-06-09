"""Service layer for contact-summary configuration writes.

Wraps the summary status/override mutations in an explicit unit of work so the
write is committed before the HTTP response is sent (issue #945), keeping
transaction ownership in the service layer rather than the controller.

This service owns the simple persistence path for the summary API endpoints
(refresh request and manual disable/override). The heavier AI generation
pipeline lives in :mod:`summary_generation_service`.
"""

from core_shared.models.contacts.entities import ContactSummary, SummaryStatus
from core_shared.models.contacts.exceptions import ContactValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.contacts.schemas import ContactSummaryUpdateData
from app.core.contacts.models.events import ContactSummaryRefreshRequested
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactSummaryRepository,
)
from app.infrastructure.unit_of_work import transactional


class ContactSummaryService:
    """Service for persisting contact-summary configuration changes."""

    def __init__(
        self,
        summary_repo: ContactSummaryRepository,
        event_publisher: ContactEventPublisher,
    ) -> None:
        self.summary_repo = summary_repo
        self.event_publisher = event_publisher

    @transactional
    async def request_refresh(
        self,
        contact_id: int,
        transaction: AsyncConnection,
    ) -> None:
        """Request a refresh of the AI-generated summary for a contact.

        Creates a pending summary record if none exists, or sets the status to
        'pending' to trigger regeneration, then publishes a
        ContactSummaryRefreshRequested event to the outbox for async processing.

        Raises ContactValidationError if summary generation is disabled for the
        contact. Committed as a single unit before the response is sent.
        """
        existing = await self.summary_repo.find_by_contact_id(contact_id)
        if existing and existing.is_disabled:
            raise ContactValidationError(
                "summary", "Summary generation is disabled for this contact"
            )

        if existing:
            await self.summary_repo.update_status(
                contact_id, SummaryStatus.PENDING.value
            )
        else:
            new_summary = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.PENDING,
            )
            await self.summary_repo.upsert(new_summary)

        # Publish outbox event to trigger async generation
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(contact_id=contact_id)
        )

    @transactional
    async def update_summary(
        self,
        contact_id: int,
        update_data: ContactSummaryUpdateData,
        transaction: AsyncConnection,
    ) -> ContactSummary:
        """Update a contact summary configuration (disable/override).

        Allows disabling AI generation or setting manual override text, and
        recomputes the summary status accordingly. Returns the persisted summary.
        Committed as a single unit before the response is sent.
        """
        existing = await self.summary_repo.find_by_contact_id(contact_id)
        if existing is None:
            existing = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.PENDING,
            )

        if update_data.is_disabled is not None:
            was_disabled = existing.is_disabled
            existing.is_disabled = update_data.is_disabled
            if update_data.is_disabled:
                existing.status = SummaryStatus.DISABLED
            elif was_disabled:
                # Re-enabling: reset status so the summary can be refreshed
                existing.status = (
                    SummaryStatus.GENERATED
                    if existing.is_user_override
                    and existing.user_override_text is not None
                    else SummaryStatus.PENDING
                )

        if update_data.user_override_text is not None:
            existing.is_user_override = True
            existing.user_override_text = update_data.user_override_text
            if not existing.is_disabled:
                existing.status = SummaryStatus.GENERATED
        elif update_data.user_override_text is None and "user_override_text" in (
            update_data.model_fields_set or set()
        ):
            existing.is_user_override = False
            existing.user_override_text = None
            # Reset status: if no AI text exists, mark as PENDING for regeneration
            if not existing.is_disabled:
                existing.status = (
                    SummaryStatus.GENERATED
                    if existing.summary_text
                    else SummaryStatus.PENDING
                )

        return await self.summary_repo.upsert(existing)
