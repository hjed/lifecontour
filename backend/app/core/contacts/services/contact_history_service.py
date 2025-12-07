"""Contact field-level history tracking service."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ContactFieldHistoryEntry,
    ContactFieldHistoryRepository,
)


class ContactHistoryService:
    """Service for tracking field-level changes in contact data."""

    def __init__(self, history_repo: ContactFieldHistoryRepository):
        self.history_repo = history_repo

    async def record_contact_change(
        self,
        contact_id: int,
        changed_fields: dict[str, Any],
        changed_by: str = "system",
        _transaction: AsyncConnection | None = None,
    ) -> None:
        """Record field changes to a contact."""
        for field_name, (old_value, new_value) in changed_fields.items():
            entry = ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by=changed_by,
            )
            await self.history_repo.record_change(entry)

    async def record_method_change(
        self,
        method_id: int,
        changed_fields: dict[str, Any],
        changed_by: str = "system",
        _transaction: AsyncConnection | None = None,
    ) -> None:
        """Record field changes to a contact method."""
        for field_name, (old_value, new_value) in changed_fields.items():
            entry = ContactFieldHistoryEntry(
                entity_type="contact_method",
                entity_id=method_id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by=changed_by,
            )
            await self.history_repo.record_change(entry)

    async def record_address_change(
        self,
        address_id: int,
        changed_fields: dict[str, Any],
        changed_by: str = "system",
        _transaction: AsyncConnection | None = None,
    ) -> None:
        """Record field changes to a contact address."""
        for field_name, (old_value, new_value) in changed_fields.items():
            entry = ContactFieldHistoryEntry(
                entity_type="contact_address",
                entity_id=address_id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by=changed_by,
            )
            await self.history_repo.record_change(entry)

    async def record_note_change(
        self,
        note_id: int,
        changed_fields: dict[str, Any],
        changed_by: str = "system",
        _transaction: AsyncConnection | None = None,
    ) -> None:
        """Record field changes to a contact note."""
        for field_name, (old_value, new_value) in changed_fields.items():
            entry = ContactFieldHistoryEntry(
                entity_type="contact_note",
                entity_id=note_id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by=changed_by,
            )
            await self.history_repo.record_change(entry)

    async def record_tag_change(
        self,
        contact_id: int,
        tag_id: int,
        action: str,
        changed_by: str = "system",
        _transaction: AsyncConnection | None = None,
    ) -> None:
        """Record a tag assignment/removal as field change."""
        entry = ContactFieldHistoryEntry(
            entity_type="contact_tag",
            entity_id=tag_id,
            field_name="contact_id",
            old_value=None if action == "assigned" else str(contact_id),
            new_value=str(contact_id) if action == "assigned" else None,
            changed_by=changed_by,
        )
        await self.history_repo.record_change(entry)

    async def get_contact_history(
        self,
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination."""
        return await self.history_repo.get_contact_history(contact_id, limit, offset)

    async def get_contact_history_count(
        self,
        contact_id: int,
        _transaction: AsyncConnection | None = None,
    ) -> int:
        """Get total count of history entries for a specific contact."""
        return await self.history_repo.get_contact_history_count(contact_id)

    async def get_entity_history(
        self,
        entity_type: str,
        entity_id: int,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific entity."""
        return await self.history_repo.get_entity_history(entity_type, entity_id)
