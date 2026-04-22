"""SQL implementation of ContactSummaryRepository."""

import json
from typing import Any

from core_shared.models.contacts.entities import ContactSummary, SummaryStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import ContactSummaryRepository


class SqlContactSummaryRepository(ContactSummaryRepository):
    """SQL implementation of ContactSummaryRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    def _row_to_entity(self, row: Any) -> ContactSummary:
        """Convert a database row to a ContactSummary domain entity."""
        suggestions = row.follow_up_suggestions
        if isinstance(suggestions, str):
            suggestions = json.loads(suggestions)
        if suggestions is None:
            suggestions = []

        return ContactSummary(
            id=row.id,
            contact_id=row.contact_id,
            summary_text=row.summary_text,
            follow_up_suggestions=suggestions,
            status=SummaryStatus(row.status),
            is_disabled=row.is_disabled,
            is_user_override=row.is_user_override,
            user_override_text=row.user_override_text,
            generated_at=row.generated_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_contact_id(self, contact_id: int) -> ContactSummary | None:
        """Find a summary by contact ID."""
        query = text(
            """
            SELECT id, contact_id, summary_text, follow_up_suggestions, status,
                   is_disabled, is_user_override, user_override_text,
                   generated_at, created_at, updated_at
            FROM contact_summaries
            WHERE contact_id = :contact_id
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def upsert(self, summary: ContactSummary) -> ContactSummary:
        """Create or update a contact summary using INSERT ON CONFLICT."""
        suggestions_json = json.dumps(summary.follow_up_suggestions)

        query = text(
            """
            INSERT INTO contact_summaries
                (contact_id, summary_text, follow_up_suggestions, status,
                 is_disabled, is_user_override, user_override_text, generated_at)
            VALUES
                (:contact_id, :summary_text, CAST(:follow_up_suggestions AS jsonb), :status,
                 :is_disabled, :is_user_override, :user_override_text, :generated_at)
            ON CONFLICT (contact_id) DO UPDATE SET
                summary_text = EXCLUDED.summary_text,
                follow_up_suggestions = EXCLUDED.follow_up_suggestions,
                status = EXCLUDED.status,
                is_disabled = EXCLUDED.is_disabled,
                is_user_override = EXCLUDED.is_user_override,
                user_override_text = EXCLUDED.user_override_text,
                generated_at = EXCLUDED.generated_at,
                updated_at = NOW()
            RETURNING id, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "contact_id": summary.contact_id,
                "summary_text": summary.summary_text,
                "follow_up_suggestions": suggestions_json,
                "status": str(summary.status),
                "is_disabled": summary.is_disabled,
                "is_user_override": summary.is_user_override,
                "user_override_text": summary.user_override_text,
                "generated_at": summary.generated_at,
            },
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert contact summary")
        summary.id = row.id
        summary.created_at = row.created_at
        summary.updated_at = row.updated_at
        return summary

    async def update_status(
        self, contact_id: int, status: str
    ) -> ContactSummary | None:
        """Update the status of a contact summary."""
        query = text(
            """
            UPDATE contact_summaries
            SET status = :status, updated_at = NOW()
            WHERE contact_id = :contact_id
            RETURNING id, contact_id, summary_text, follow_up_suggestions, status,
                      is_disabled, is_user_override, user_override_text,
                      generated_at, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query, {"contact_id": contact_id, "status": status}
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)
