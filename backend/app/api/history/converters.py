"""Converter from the domain ``FieldHistoryEntry`` to JSON:API resources."""

from datetime import datetime

from app.api.history.schemas import HistoryAttributes, HistoryResource
from app.core.history.models import FieldHistoryEntry


class HistoryConverter:
    """Converts a ``FieldHistoryEntry`` into a JSON:API ``HistoryResource``."""

    @staticmethod
    def to_resource(
        entry: FieldHistoryEntry, resource_type: str = "journal_history"
    ) -> HistoryResource:
        """Convert a history entry to an API resource.

        ``resource_type`` parameterises the JSON:API ``type`` so the same shared
        schema serves journals (``journal_history``) and any future entity.
        """
        created_at: datetime | None = None
        if entry.created_at:
            if isinstance(entry.created_at, str):
                try:
                    created_at = datetime.fromisoformat(entry.created_at)
                except ValueError:
                    created_at = None
            else:
                created_at = entry.created_at

        attributes = HistoryAttributes(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            field_name=entry.field_name,
            old_value=entry.old_value,
            new_value=entry.new_value,
            changed_by=entry.changed_by,
            source=entry.source.value
            if hasattr(entry.source, "value")
            else str(entry.source),
            created_at=created_at,
        )

        if entry.id is None:
            raise ValueError("Cannot serialize history entry without ID")

        return HistoryResource(
            type=resource_type,
            id=str(entry.id),
            attributes=attributes,
        )
