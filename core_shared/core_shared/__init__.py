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
from core_shared.encryption import (
    EncryptionServiceProtocol,
    FernetEncryptionService,
    generate_encryption_key,
)
from core_shared.models import (
    Base,
    ExternalReference,
    SyncMetadata,
    SyncStatus,
    UserGoogleAuth,
)

__all__ = [
    # Models
    "Base",
    "SyncMetadata",
    "ExternalReference",
    "SyncStatus",
    "UserGoogleAuth",
    # Database utilities
    "create_async_engine_from_url",
    "create_session_factory",
    # Integration base classes
    "BaseIntegrationService",
    "SyncResult",
    "SyncDirection",
    "IntegrationError",
    "SyncError",
    "TransformationError",
    # Encryption utilities
    "EncryptionServiceProtocol",
    "FernetEncryptionService",
    "generate_encryption_key",
]
