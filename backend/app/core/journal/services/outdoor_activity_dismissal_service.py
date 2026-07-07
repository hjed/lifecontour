"""Service layer for outdoor-activity review dismissals.

Wraps each dismissal mutation in an explicit unit of work so the write is
committed before the HTTP response is sent (issue #945), keeping transaction
ownership in the service layer rather than the controller. The store is distinct
from the merge ``journal_review_items`` queue.
"""

from core_shared.models.history import Provenance
from core_shared.models.journals import OutdoorActivityDismissal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import OutdoorActivityDismissalRepository
from app.infrastructure.unit_of_work import transactional


class OutdoorActivityDismissalService:
    """Service for persisting outdoor-activity review dismissals."""

    def __init__(self, dismissal_repo: OutdoorActivityDismissalRepository) -> None:
        self.dismissal_repo = dismissal_repo

    @transactional
    async def dismiss(
        self,
        journal_id: int,
        user_id: str,
        provenance: Provenance,
        transaction: AsyncConnection,
    ) -> OutdoorActivityDismissal:
        """Dismiss a journal from the review as a committed unit of work.

        Idempotent: re-dismissing keeps a single dismissal and refreshes its
        provenance. ``provenance`` records where the dismissal came from (UI/MCP).
        """
        return await self.dismissal_repo.dismiss(
            journal_id=journal_id, user_id=user_id, provenance=provenance
        )

    @transactional
    async def undismiss(
        self,
        journal_id: int,
        user_id: str,
        transaction: AsyncConnection,
    ) -> bool:
        """Un-dismiss a journal as a committed unit of work.

        Idempotent: returns ``True`` if a dismissal was removed, ``False`` if the
        journal was not dismissed.
        """
        return await self.dismissal_repo.undismiss(
            journal_id=journal_id, user_id=user_id
        )
