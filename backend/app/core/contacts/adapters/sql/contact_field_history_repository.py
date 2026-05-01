"""SQL implementation of ContactFieldHistoryRepository."""

from core_shared.models.contacts.value_objects import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ContactFieldHistoryEntry,
    ContactFieldHistoryRepository,
)


class SqlContactFieldHistoryRepository(ContactFieldHistoryRepository):
    """SQL implementation of ContactFieldHistoryRepository using SQLAlchemy Core."""

    @staticmethod
    def _parse_provenance(source: str | None) -> Provenance:
        if not source:
            return Provenance.SYSTEM
        try:
            return Provenance(source)
        except ValueError:
            return Provenance.SYSTEM

    # Shared WHERE clause for contact history queries
    # Matches history entries for the contact itself and all related entities
    _CONTACT_HISTORY_WHERE_CLAUSE = """
        (entity_type = 'contact' AND entity_id = :contact_id)
        OR (entity_type IN ('contact_method', 'contact_address', 'contact_note', 'contact_tag', 'contact_relationship', 'contact_important_date')
            AND entity_id IN (
                SELECT id FROM contact_methods WHERE contact_id = :contact_id
                UNION
                SELECT id FROM contact_addresses WHERE contact_id = :contact_id
                UNION
                SELECT id FROM contact_notes WHERE contact_id = :contact_id
                UNION
                SELECT tag_id FROM contact_tags WHERE contact_id = :contact_id
                UNION
                SELECT id FROM contact_relationships WHERE from_contact_id = :contact_id OR to_contact_id = :contact_id
                UNION
                SELECT id FROM contact_important_dates WHERE contact_id = :contact_id
            ))
    """

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def get_contact_history(
        self, contact_id: int, limit: int = 50, offset: int = 0
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination."""
        query = text(
            f"""
            SELECT id, entity_type, entity_id, field_name, old_value, new_value,
                   changed_by, source, created_at
            FROM contact_field_history
            WHERE {self._CONTACT_HISTORY_WHERE_CLAUSE}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        )
        result = await self.conn.execute(
            query, {"contact_id": contact_id, "limit": limit, "offset": offset}
        )

        entries = []
        for row in result.fetchall():
            entry = ContactFieldHistoryEntry(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                field_name=row.field_name,
                old_value=row.old_value,
                new_value=row.new_value,
                changed_by=row.changed_by,
                source=self._parse_provenance(row.source),
                id=row.id,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            entries.append(entry)

        return entries

    async def get_contact_history_count(self, contact_id: int) -> int:
        """Get total count of history entries for a specific contact."""
        query = text(
            f"""
            SELECT COUNT(*) as total
            FROM contact_field_history
            WHERE {self._CONTACT_HISTORY_WHERE_CLAUSE}
        """
        )
        result = await self.conn.execute(query, {"contact_id": contact_id})
        row = result.fetchone()
        return row.total if row else 0

    async def get_entity_history(
        self, entity_type: str, entity_id: int
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific entity."""
        query = text(
            """
            SELECT id, entity_type, entity_id, field_name, old_value, new_value,
                   changed_by, source, created_at
            FROM contact_field_history
            WHERE entity_type = :entity_type AND entity_id = :entity_id
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(
            query, {"entity_type": entity_type, "entity_id": entity_id}
        )

        entries = []
        for row in result.fetchall():
            entry = ContactFieldHistoryEntry(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                field_name=row.field_name,
                old_value=row.old_value,
                new_value=row.new_value,
                changed_by=row.changed_by,
                source=self._parse_provenance(row.source),
                id=row.id,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            entries.append(entry)

        return entries

    async def record_change(
        self, entry: ContactFieldHistoryEntry
    ) -> ContactFieldHistoryEntry:
        """Record a field change in history."""
        query = text(
            """
            INSERT INTO contact_field_history
            (entity_type, entity_id, field_name, old_value, new_value, changed_by, source)
            VALUES (:entity_type, :entity_id, :field_name, :old_value, :new_value, :changed_by, :source)
            RETURNING id, created_at
        """
        )
        result = await self.conn.execute(
            query,
            {
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "field_name": entry.field_name,
                "old_value": entry.old_value,
                "new_value": entry.new_value,
                "changed_by": entry.changed_by,
                "source": entry.source.value,
            },
        )
        row = result.fetchone()
        if row is None:
            raise RuntimeError("Failed to insert contact field history entry")
        entry.id = row.id
        entry.created_at = row.created_at.isoformat() if row.created_at else None

        return entry

    async def record_multiple_changes(
        self, entries: list[ContactFieldHistoryEntry]
    ) -> list[ContactFieldHistoryEntry]:
        """Record multiple field changes in history."""
        saved_entries = []
        for entry in entries:
            saved_entry = await self.record_change(entry)
            saved_entries.append(saved_entry)
        return saved_entries

    async def get_field_history(
        self, entity_id: int, field_name: str, entity_type: str = "contact"
    ) -> list[ContactFieldHistoryEntry]:
        """Get history for a specific field of an entity."""
        query = text(
            """
            SELECT id, entity_type, entity_id, field_name, old_value, new_value,
                   changed_by, source, created_at
            FROM contact_field_history
            WHERE entity_type = :entity_type AND entity_id = :entity_id AND field_name = :field_name
            ORDER BY created_at DESC
        """
        )
        result = await self.conn.execute(
            query,
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_name": field_name,
            },
        )

        entries = []
        for row in result.fetchall():
            entry = ContactFieldHistoryEntry(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                field_name=row.field_name,
                old_value=row.old_value,
                new_value=row.new_value,
                changed_by=row.changed_by,
                source=self._parse_provenance(row.source),
                id=row.id,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            entries.append(entry)

        return entries

    async def get_changes_by_user(
        self, changed_by: str, limit: int = 50
    ) -> list[ContactFieldHistoryEntry]:
        """Get changes made by a specific user."""
        query = text(
            """
            SELECT id, entity_type, entity_id, field_name, old_value, new_value,
                   changed_by, source, created_at
            FROM contact_field_history
            WHERE changed_by = :changed_by
            ORDER BY created_at DESC
            LIMIT :limit
        """
        )
        result = await self.conn.execute(
            query, {"changed_by": changed_by, "limit": limit}
        )

        entries = []
        for row in result.fetchall():
            entry = ContactFieldHistoryEntry(
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                field_name=row.field_name,
                old_value=row.old_value,
                new_value=row.new_value,
                changed_by=row.changed_by,
                source=self._parse_provenance(row.source),
                id=row.id,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            entries.append(entry)

        return entries
