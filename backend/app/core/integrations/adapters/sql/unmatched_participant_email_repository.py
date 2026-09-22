"""SQL repository for participant emails that matched no contact."""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.models.unmatched_participant import (
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
