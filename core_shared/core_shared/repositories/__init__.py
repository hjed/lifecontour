"""
Repositories for shared data access across workers and main application.

This package contains repository classes that provide data access methods
for shared models. These repositories can be used by both the main application
and integration workers.
"""

from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)
from core_shared.repositories.sync_job_repository import SyncJobRepository

__all__ = ["ExternalReferenceRepository", "SyncJobRepository"]
