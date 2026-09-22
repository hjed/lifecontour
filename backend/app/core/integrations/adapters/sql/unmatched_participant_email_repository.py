"""SQL repository for participant emails that matched no contact."""

from collections.abc import Sequence

from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.models.unmatched_participant import (
    ContactSuggestion,
    UnmatchedParticipantEmail,
)


class SqlUnmatchedParticipantEmailRepository:
    """Per-journal record of the participant emails inbound sync could not resolve."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def replace_for_journal(
        self, journal_id: int, entries: Sequence[UnmatchedParticipantEmail]
    ) -> None:
        """Make ``entries`` the journal's complete set of unmatched emails.

        Each sync reports the whole participant list, so emails no longer on
        the journal -- or that now resolve to a contact -- are removed, and the
        rest are upserted with what the integration last said about them.
        """
        emails = [entry.email for entry in entries]
        await self.connection.execute(
            text(
                """
                DELETE FROM journal_unmatched_participant_emails
                WHERE journal_id = :journal_id
                  AND NOT (email = ANY(:emails))
                """
            ),
            {"journal_id": journal_id, "emails": emails},
        )
        for entry in entries:
            await self.connection.execute(
                text(
                    """
                    INSERT INTO journal_unmatched_participant_emails
                        (journal_id, email, display_name, relationship_type,
                         status, role)
                    VALUES
                        (:journal_id, :email, :display_name, :relationship_type,
                         :status, :role)
                    ON CONFLICT (journal_id, email) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        relationship_type = EXCLUDED.relationship_type,
                        status = EXCLUDED.status,
                        role = EXCLUDED.role,
                        updated_at = NOW()
                    """
                ),
                {
                    "journal_id": journal_id,
                    "email": entry.email,
                    "display_name": entry.display_name,
                    "relationship_type": entry.relationship_type.value,
                    "status": entry.status.value if entry.status else None,
                    "role": entry.role.value if entry.role else None,
                },
            )

    async def list_candidates(
        self, user_id: str, min_journals: int
    ) -> list[ContactSuggestion]:
        """Emails on at least ``min_journals`` of the user's journals.

        Emails a contact already holds (compared trimmed and case-insensitively)
        and emails the user has ignored are left out. Most-seen first.
        """
        result = await self.connection.execute(
            text(
                """
                SELECT u.email,
                       mode() WITHIN GROUP (ORDER BY u.display_name)
                           AS display_name,
                       COUNT(DISTINCT u.journal_id) AS event_count,
                       MAX(j.event_date_range_start) AS last_seen_at
                FROM journal_unmatched_participant_emails u
                JOIN journals j ON j.id = u.journal_id
                WHERE j.user_id = :user_id
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_methods cm
                      WHERE cm.method_type = 'email'
                        AND LOWER(BTRIM(cm.value)) = u.email
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_suggestion_ignores i
                      WHERE i.user_id = :user_id
                        AND i.email = u.email
                  )
                GROUP BY u.email
                HAVING COUNT(DISTINCT u.journal_id) >= :min_journals
                ORDER BY event_count DESC, u.email
                """
            ),
            {"user_id": user_id, "min_journals": min_journals},
        )
        return [
            ContactSuggestion(
                email=row.email,
                display_name=row.display_name,
                event_count=row.event_count,
                last_seen_at=row.last_seen_at,
            )
            for row in result.fetchall()
        ]

    async def list_for_email(
        self, user_id: str, email: str
    ) -> list[UnmatchedParticipantEmail]:
        """Every one of the user's journals ``email`` is recorded as unmatched on."""
        result = await self.connection.execute(
            text(
                """
                SELECT u.journal_id, u.email, u.display_name,
                       u.relationship_type, u.status, u.role
                FROM journal_unmatched_participant_emails u
                JOIN journals j ON j.id = u.journal_id
                WHERE j.user_id = :user_id
                  AND u.email = :email
                ORDER BY u.journal_id
                """
            ),
            {"user_id": user_id, "email": email},
        )
        return [
            UnmatchedParticipantEmail(
                journal_id=row.journal_id,
                email=row.email,
                relationship_type=JournalContactRelationshipType(row.relationship_type),
                display_name=row.display_name,
                status=AttendeeStatus(row.status) if row.status else None,
                role=ContactEventRole(row.role) if row.role else None,
            )
            for row in result.fetchall()
        ]

    async def delete_for_email(self, user_id: str, email: str) -> None:
        """Forget ``email`` on all of the user's journals."""
        await self.connection.execute(
            text(
                """
                DELETE FROM journal_unmatched_participant_emails u
                USING journals j
                WHERE j.id = u.journal_id
                  AND j.user_id = :user_id
                  AND u.email = :email
                """
            ),
            {"user_id": user_id, "email": email},
        )
