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
from core_shared.database import create_engine_from_url, get_database_url
from core_shared.models import Base, ExternalReference, SyncMetadata, SyncStatus, UserGoogleAuth

__all__ = [
    "Base",
    "SyncMetadata",
    "ExternalReference",
    "SyncStatus",
    "UserGoogleAuth",
    "get_database_url",
    "create_engine_from_url",
    "BaseIntegrationService",
    "SyncResult",
    "SyncDirection",
    "IntegrationError",
    "SyncError",
    "TransformationError",
]
