"""SQL repository for the per-user contact-suggestion ignore list."""

from core_shared.models.history import Provenance
from core_shared.models.participant_email import normalise_participant_email
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.models.unmatched_participant import (
    IgnoredContactSuggestion,
)


class SqlContactSuggestionIgnoreRepository:
    """Emails a user never wants suggested as contacts.

    A row's presence hides the email from that user's suggestions; ``unignore``
    deletes the row. Emails are stored and matched in their canonical form,
    whatever form the caller holds them in.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def ignore(
        self, user_id: str, email: str, provenance: Provenance
    ) -> IgnoredContactSuggestion:
        """Ignore ``email`` for the user, returning the stored entry.

        Ignoring it again keeps the entry as it is -- its first provenance and
        creation time -- and returns that, so a caller reports what is stored
        rather than what it asked for. The no-op ``DO UPDATE`` is what lets
        ``RETURNING`` report an entry that was already there.
        """
        row = (
            await self.connection.execute(
                text(
                    """
                    INSERT INTO contact_suggestion_ignores
                        (user_id, email, provenance)
                    VALUES (:user_id, :email, :provenance)
                    ON CONFLICT (user_id, email) DO UPDATE SET
                        provenance = contact_suggestion_ignores.provenance
                    RETURNING email, provenance, created_at
                    """
                ),
                {
                    "user_id": user_id,
                    "email": normalise_participant_email(email),
                    "provenance": provenance.value,
                },
            )
        ).one()
        return IgnoredContactSuggestion(
            email=row.email,
            provenance=Provenance(row.provenance),
            created_at=row.created_at,
        )

    async def unignore(self, user_id: str, email: str) -> bool:
        """Stop ignoring ``email``; whether it was ignored."""
        result = await self.connection.execute(
            text(
                """
                DELETE FROM contact_suggestion_ignores
                WHERE user_id = :user_id AND email = :email
                RETURNING email
                """
            ),
            {"user_id": user_id, "email": normalise_participant_email(email)},
        )
        return result.fetchone() is not None

    async def list_ignored(self, user_id: str) -> list[IgnoredContactSuggestion]:
        """The user's ignored emails, alphabetically."""
        result = await self.connection.execute(
            text(
                """
                SELECT email, provenance, created_at
                FROM contact_suggestion_ignores
                WHERE user_id = :user_id
                ORDER BY email
                """
            ),
            {"user_id": user_id},
        )
        return [
            IgnoredContactSuggestion(
                email=row.email,
                provenance=Provenance(row.provenance),
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]
