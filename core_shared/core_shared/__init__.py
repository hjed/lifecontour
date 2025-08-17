"""
Core shared package for Personal Management System integrations.

This package contains shared models, database utilities, and common patterns
used across the main application and integration workers.
"""

__version__ = "0.1.0"

from core_shared.base_service import (
    BaseIntegrationService,
    IntegrationError,
    SyncDirection,
    SyncError,
    SyncResult,
    TransformationError,
)

# Only import what's available to avoid circular imports
from core_shared.database.engine import (
    create_async_engine_from_url,
    create_session_factory,
)
from core_shared.models import Base, ExternalReference, SyncMetadata, SyncStatus

__all__ = [
    "Base",
    "SyncMetadata",
    "ExternalReference",
    "SyncStatus",
    "create_async_engine_from_url",
    "create_session_factory",
    "BaseIntegrationService",
    "SyncResult",
    "SyncDirection",
    "IntegrationError",
    "SyncError",
    "TransformationError",
]
