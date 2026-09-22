"""Read access to the participant emails inbound sync could not resolve.

The backend writes ``journal_unmatched_participant_emails``; integration
workers read it to decide whether an unchanged event still needs to be synced
once so the backend can record its unmatched participants.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class UnmatchedParticipantRepository:
    """Queries over a journal's recorded unmatched participant emails.

    Args:
        connection: An async SQLAlchemy connection.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._conn = connection

    async def has_unrecorded_unmatched_email(
        self, user_id: str, journal_id: int, emails: Sequence[str]
    ) -> bool:
        """Whether any of ``emails`` matches no contact and is not yet recorded.

        Args:
            user_id: Owner of the journal; a journal of another user never
                matches.
            journal_id: The journal the emails were seen on.
            emails: Lower-cased participant emails.
        """
        if not emails:
            return False
        result = await self._conn.execute(
            text("""
                SELECT 1
                FROM journals j
                CROSS JOIN unnest(CAST(:emails AS text[])) AS attendee(email)
                WHERE j.id = :journal_id
                  AND j.user_id = :user_id
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_methods cm
                      WHERE cm.method_type = 'email'
                        AND lower(cm.value) = attendee.email
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM journal_unmatched_participant_emails u
                      WHERE u.journal_id = j.id
                        AND u.email = attendee.email
                  )
                LIMIT 1
            """),
            {"emails": list(emails), "journal_id": journal_id, "user_id": user_id},
        )
        return result.fetchone() is not None
