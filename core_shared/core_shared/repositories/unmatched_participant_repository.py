"""Queries deciding whether a synced event's participants are up to date.

The backend links participant emails to contacts and records the rest in
``journal_unmatched_participant_emails``. Integration workers skip an event
whose version is unchanged, so they ask these queries whether syncing it once
more would still change its journal's participants. Emails are compared in
their canonical form (``normalise_participant_email``).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class UnmatchedParticipantRepository:
    """Queries over a journal's participant emails, linked and unmatched.

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
            emails: Participant emails in canonical form.
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
                        AND LOWER(BTRIM(cm.value)) = attendee.email
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

    async def has_unlinked_contact_email(
        self, user_id: str, journal_id: int, emails: Sequence[str]
    ) -> bool:
        """Whether any of ``emails`` belongs to a contact the journal lacks.

        Args:
            user_id: Owner of the journal; a journal of another user never
                matches.
            journal_id: The journal the emails were seen on.
            emails: Participant emails in canonical form.
        """
        if not emails:
            return False
        result = await self._conn.execute(
            text("""
                SELECT 1
                FROM journals j
                JOIN contact_methods cm
                  ON cm.method_type = 'email'
                 AND LOWER(BTRIM(cm.value)) = ANY(CAST(:emails AS text[]))
                WHERE j.id = :journal_id
                  AND j.user_id = :user_id
                  AND NOT EXISTS (
                      SELECT 1 FROM journal_contact_relationships jc
                      WHERE jc.contact_id = cm.contact_id
                        AND jc.journal_id = j.id
                  )
                LIMIT 1
            """),
            {"emails": list(emails), "journal_id": journal_id, "user_id": user_id},
        )
        return result.fetchone() is not None
