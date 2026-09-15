"""SQL implementation of ContactSummaryRepository."""

import json
from typing import Any

from core_shared.models.contacts.entities import (
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ClaimedRefresh,
    ContactSummaryRepository,
)


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
            disabled_reason=(
                SummaryDisabledReason(row.disabled_reason)
                if row.disabled_reason is not None
                else None
            ),
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
                   is_disabled, disabled_reason, is_user_override, user_override_text,
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
                 is_disabled, disabled_reason, is_user_override, user_override_text,
                 generated_at)
            VALUES
                (:contact_id, :summary_text, CAST(:follow_up_suggestions AS jsonb), :status,
                 :is_disabled, :disabled_reason, :is_user_override, :user_override_text,
                 :generated_at)
            ON CONFLICT (contact_id) DO UPDATE SET
                summary_text = EXCLUDED.summary_text,
                follow_up_suggestions = EXCLUDED.follow_up_suggestions,
                status = EXCLUDED.status,
                is_disabled = EXCLUDED.is_disabled,
                disabled_reason = EXCLUDED.disabled_reason,
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
                "disabled_reason": (
                    str(summary.disabled_reason) if summary.disabled_reason else None
                ),
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
                      is_disabled, disabled_reason, is_user_override,
                      user_override_text, generated_at, created_at, updated_at
        """
        )
        result = await self.conn.execute(
            query, {"contact_id": contact_id, "status": status}
        )
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    async def mark_refresh_requested(self, contact_id: int) -> None:
        """Record a buffered refresh request, resetting the debounce timer.

        Creates the summary row (status takes its server default 'pending')
        when none exists; overwrites ``refresh_requested_at`` on every call so
        the sweeper only dispatches after the contact has been quiet for the
        full buffer window. No-op for summaries the user disabled; an
        auto-paused (low-activity) summary is still marked so it is re-evaluated.
        """
        query = text(
            """
            INSERT INTO contact_summaries (contact_id, refresh_requested_at)
            VALUES (:contact_id, NOW())
            ON CONFLICT (contact_id) DO UPDATE SET
                refresh_requested_at = NOW(),
                updated_at = NOW()
            WHERE contact_summaries.disabled_reason IS DISTINCT FROM 'user'
        """
        )
        await self.conn.execute(query, {"contact_id": contact_id})

    async def clear_refresh_request(self, contact_id: int) -> None:
        """Clear any pending buffered refresh marker for a contact."""
        query = text(
            """
            UPDATE contact_summaries
            SET refresh_requested_at = NULL, updated_at = NOW()
            WHERE contact_id = :contact_id
              AND refresh_requested_at IS NOT NULL
        """
        )
        await self.conn.execute(query, {"contact_id": contact_id})

    async def claim_due_refreshes(
        self, buffer_seconds: int, limit: int
    ) -> list[ClaimedRefresh]:
        """Atomically claim contacts whose buffered refresh is due.

        Clears markers older than the buffer window and returns the affected
        contacts, oldest first, flagging those the user disabled. The cutoff is
        computed with the database's NOW() — the same clock that stamps the
        marker in mark_refresh_requested — so app/DB clock drift cannot
        stretch or shrink the debounce window. ``FOR UPDATE SKIP LOCKED``
        makes concurrent sweeps safe: a row claimed by one sweep is invisible
        to the next, so a refresh is dispatched exactly once.
        """
        query = text(
            """
            WITH due AS (
                SELECT contact_id, refresh_requested_at
                FROM contact_summaries
                WHERE refresh_requested_at IS NOT NULL
                  AND refresh_requested_at
                      <= NOW() - make_interval(secs => :buffer_seconds)
                ORDER BY refresh_requested_at
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
            )
            UPDATE contact_summaries cs
            SET refresh_requested_at = NULL, updated_at = NOW()
            FROM due
            WHERE cs.contact_id = due.contact_id
            RETURNING cs.contact_id,
                      cs.disabled_reason IS NOT DISTINCT FROM 'user'
                          AS is_user_disabled,
                      due.refresh_requested_at
        """
        )
        result = await self.conn.execute(
            query, {"buffer_seconds": buffer_seconds, "limit": limit}
        )
        rows = sorted(result.fetchall(), key=lambda row: row.refresh_requested_at)
        return [
            ClaimedRefresh(
                contact_id=row.contact_id, is_user_disabled=row.is_user_disabled
            )
            for row in rows
        ]
