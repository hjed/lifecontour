"""SQL implementation of the outdoor-activity dismissal repository."""

from __future__ import annotations

from core_shared.models.history import Provenance
from core_shared.models.journals import OutdoorActivityDismissal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import OutdoorActivityDismissalRepository


class SqlOutdoorActivityDismissalRepository(OutdoorActivityDismissalRepository):
    """Repository for journal-scoped outdoor-activity review dismissals.

    A row's presence means the journal is dismissed for that user; ``undismiss``
    deletes the row. Distinct from the merge ``journal_review_items`` queue.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def dismiss(
        self, journal_id: int, user_id: str, provenance: Provenance
    ) -> OutdoorActivityDismissal:
        """Dismiss a journal for a user (idempotent upsert).

        Re-dismissing keeps the original ``created_at`` but refreshes
        ``provenance`` and ``updated_at`` on conflict, so it is idempotent.
        """
        stmt = text(
            """
            INSERT INTO outdoor_activity_dismissals
                (journal_id, user_id, provenance, updated_at)
            VALUES (:journal_id, :user_id, :provenance, NOW())
            ON CONFLICT (user_id, journal_id)
            DO UPDATE SET
                provenance = EXCLUDED.provenance,
                updated_at = NOW()
            RETURNING journal_id, user_id, provenance, created_at, updated_at
            """
        )
        result = await self.connection.execute(
            stmt,
            {
                "journal_id": journal_id,
                "user_id": user_id,
                "provenance": provenance.value,
            },
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError("Failed to record outdoor activity dismissal")

        return OutdoorActivityDismissal(
            journal_id=int(row.journal_id),
            user_id=str(row.user_id),
            provenance=Provenance(row.provenance),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def undismiss(self, journal_id: int, user_id: str) -> bool:
        """Un-dismiss a journal for a user (idempotent delete).

        Returns ``True`` if a dismissal row was removed, ``False`` if none
        existed.
        """
        stmt = text(
            """
            DELETE FROM outdoor_activity_dismissals
            WHERE user_id = :user_id AND journal_id = :journal_id
            """
        )
        result = await self.connection.execute(
            stmt, {"user_id": user_id, "journal_id": journal_id}
        )
        return result.rowcount > 0

    async def list_dismissed_journal_ids(self, user_id: str) -> set[int]:
        """Return the set of journal ids the user has dismissed."""
        stmt = text(
            """
            SELECT journal_id
            FROM outdoor_activity_dismissals
            WHERE user_id = :user_id
            """
        )
        result = await self.connection.execute(stmt, {"user_id": user_id})
        return {int(row.journal_id) for row in result.fetchall()}
