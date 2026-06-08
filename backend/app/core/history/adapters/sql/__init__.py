"""SQL adapters for the shared history domain."""

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)

__all__ = ["SqlFieldHistoryRepository"]
