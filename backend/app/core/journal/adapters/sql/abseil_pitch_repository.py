"""SQL implementation of AbseilPitchRepository."""

from typing import Any

from core_shared.models.journals import AbseilPitch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import AbseilPitchRepository


class SqlAbseilPitchRepository(AbseilPitchRepository):
    """SQL implementation of AbseilPitchRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_entity(self, row: Any) -> AbseilPitch:
        """Convert a database row to an AbseilPitch entity."""
        return AbseilPitch(
            id=row.id,
            journal_id=row.journal_id,
            pitch_number=row.pitch_number,
            height=row.height,
            anchor_location=row.anchor_location,
            anchor_type=row.anchor_type,
            did_rescue=row.did_rescue,
            did_setup=row.did_setup,
            notes=row.notes,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save(self, pitch: AbseilPitch) -> AbseilPitch:
        """
        Save an abseil pitch (insert or update) using atomic UPSERT.

        Uses ON CONFLICT on (journal_id, pitch_number) to update an existing
        pitch or insert a new one.

        Args:
            pitch: The abseil pitch to save

        Returns:
            The saved pitch with updated fields (id, timestamps)
        """
        query = text(
            """
            INSERT INTO abseil_pitches (
                journal_id, pitch_number, height, anchor_location,
                anchor_type, did_rescue, did_setup, notes
            )
            VALUES (
                :journal_id, :pitch_number, :height, :anchor_location,
                :anchor_type, :did_rescue, :did_setup, :notes
            )
            ON CONFLICT (journal_id, pitch_number) DO UPDATE SET
                height = EXCLUDED.height,
                anchor_location = EXCLUDED.anchor_location,
                anchor_type = EXCLUDED.anchor_type,
                did_rescue = EXCLUDED.did_rescue,
                did_setup = EXCLUDED.did_setup,
                notes = EXCLUDED.notes,
                updated_at = now()
            RETURNING id, journal_id, pitch_number, height, anchor_location,
                      anchor_type, did_rescue, did_setup, notes, created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": pitch.journal_id,
                "pitch_number": pitch.pitch_number,
                "height": pitch.height,
                "anchor_location": pitch.anchor_location,
                "anchor_type": pitch.anchor_type,
                "did_rescue": pitch.did_rescue,
                "did_setup": pitch.did_setup,
                "notes": pitch.notes,
            },
        )
        row = result.fetchone()
        return self._row_to_entity(row)

    async def find_by_journal_id(self, journal_id: int) -> list[AbseilPitch]:
        """Find all pitches for a journal, ordered by pitch_number."""
        query = text(
            """
            SELECT id, journal_id, pitch_number, height, anchor_location,
                   anchor_type, did_rescue, did_setup, notes, created_at, updated_at
            FROM abseil_pitches
            WHERE journal_id = :journal_id
            ORDER BY pitch_number
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()
        return [self._row_to_entity(row) for row in rows]

    async def delete_by_journal_id(self, journal_id: int) -> None:
        """Delete all pitches for a journal."""
        query = text("DELETE FROM abseil_pitches WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

    async def delete(self, pitch_id: int) -> None:
        """Delete a single pitch by ID."""
        query = text("DELETE FROM abseil_pitches WHERE id = :pitch_id")
        await self.conn.execute(query, {"pitch_id": pitch_id})
