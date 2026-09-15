"""Service layer for contact-summary configuration writes.

Wraps the summary status/override mutations in an explicit unit of work so the
write is committed before the HTTP response is sent (issue #945), keeping
transaction ownership in the service layer rather than the controller.

This service owns the simple persistence path for the summary API endpoints
(refresh request and manual disable/override). The heavier AI generation
pipeline lives in :mod:`summary_generation_service`.
"""

from dataclasses import dataclass

from core_shared.models.contacts.entities import (
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)
from core_shared.models.contacts.exceptions import ContactValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import ContactSummaryRefreshDue
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactSummaryRepository,
)
from app.infrastructure.unit_of_work import transactional


@dataclass(frozen=True)
class ContactSummaryUpdate:
    """API-agnostic payload for a contact-summary configuration change.

    ``override_text_provided`` preserves the tri-state the API layer expresses
    via ``model_fields_set``: ``True`` when the caller explicitly set
    ``user_override_text`` (including to ``None`` to clear it), ``False`` when
    the field was omitted (leave any existing override untouched).
    """

    is_disabled: bool | None = None
    user_override_text: str | None = None
    override_text_provided: bool = False


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
        """Request an immediate refresh of the AI-generated summary for a contact.

        Creates a pending summary record if none exists, or sets the status to
        'pending' to trigger regeneration, then publishes a
        ContactSummaryRefreshDue event to the outbox for async processing.
        Manual refresh bypasses the rolling-debounce buffer that automated
        triggers go through, and absorbs any queued buffered request so the
        user's click costs a single generation.

        Raises ContactValidationError if the user disabled summary generation
        for the contact. An auto-paused (low-activity) summary keeps its
        DISABLED status and is queued anyway: the generator re-evaluates its
        activity and resumes it if there is now enough. Committed as a single
        unit before the response is sent.
        """
        existing = await self.summary_repo.find_by_contact_id(
            contact_id, for_update=True
        )
        if existing and existing.is_user_disabled:
            raise ContactValidationError(
                "summary", "Summary generation is disabled for this contact"
            )

        if existing and existing.is_disabled:
            pass  # Auto-paused: the generator decides whether it resumes
        elif existing:
            await self.summary_repo.update_status(
                contact_id, SummaryStatus.PENDING.value
            )
        else:
            new_summary = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.PENDING,
            )
            await self.summary_repo.upsert(new_summary)

        # Absorb any buffered request queued by automated triggers
        await self.summary_repo.clear_refresh_request(contact_id)

        # Publish outbox event to trigger async generation immediately
        await self.event_publisher.publish(
            ContactSummaryRefreshDue(contact_id=contact_id)
        )

    @transactional
    async def update_summary(
        self,
        contact_id: int,
        update: ContactSummaryUpdate,
        transaction: AsyncConnection,
    ) -> ContactSummary:
        """Update a contact summary configuration (disable/override).

        Allows disabling AI generation or setting manual override text, and
        recomputes the summary status accordingly. Disabling records the user's
        choice, which nothing automatic undoes. Re-enabling a disabled summary
        queues generation immediately rather than waiting for other activity.
        Returns the persisted summary. Committed as a single unit before the
        response is sent.
        """
        # Locked read: the change is computed from the row it overwrites, so an
        # in-flight generation is waited for rather than clobbered or lost.
        existing = await self.summary_repo.find_by_contact_id(
            contact_id, for_update=True
        )
        if existing is None:
            existing = ContactSummary(
                contact_id=contact_id,
                status=SummaryStatus.PENDING,
            )

        re_enabled = False
        if update.is_disabled is not None:
            if update.is_disabled:
                existing.disable(SummaryDisabledReason.USER)
            elif existing.is_disabled:
                # Re-enabling: reset status so the summary can be refreshed
                existing.enable()
                re_enabled = True
                existing.status = (
                    SummaryStatus.GENERATED
                    if existing.is_user_override
                    and existing.user_override_text is not None
                    else SummaryStatus.PENDING
                )

        if update.user_override_text is not None:
            existing.is_user_override = True
            existing.user_override_text = update.user_override_text
            if not existing.is_disabled:
                existing.status = SummaryStatus.GENERATED
        elif update.override_text_provided and update.user_override_text is None:
            existing.is_user_override = False
            existing.user_override_text = None
            # Reset status: if no AI text exists, mark as PENDING for regeneration
            if not existing.is_disabled:
                existing.status = (
                    SummaryStatus.GENERATED
                    if existing.summary_text
                    else SummaryStatus.PENDING
                )

        persisted = await self.summary_repo.upsert(existing)

        if re_enabled:
            await self.summary_repo.clear_refresh_request(contact_id)
            await self.event_publisher.publish(
                ContactSummaryRefreshDue(contact_id=contact_id)
            )

        return persisted
