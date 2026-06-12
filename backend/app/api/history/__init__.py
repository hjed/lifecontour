"""Shared JSON:API schemas and converters for entity-agnostic field history.

These schemas back the journal history endpoint (ITER12-002 Phase 2) and are the
shared shape contacts adopt as the unified history system lands. They mirror the
existing ``ContactHistory*`` schemas but carry no contact-specific ``type``.
"""

from app.api.history.converters import HistoryConverter
from app.api.history.schemas import (
    HistoryAttributes,
    HistoryListResponse,
    HistoryResource,
)

__all__ = [
    "HistoryAttributes",
    "HistoryConverter",
    "HistoryListResponse",
    "HistoryResource",
]
