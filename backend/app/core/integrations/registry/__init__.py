"""
Pluggable integration registry.

Provides a generic registry that aggregates integration status, capabilities,
and sync summaries from pluggable providers. Each integration (Google, Strava,
etc.) implements the ``IntegrationProvider`` protocol and is registered via
Dishka DI.
"""

from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
    SyncSummary,
)
from app.core.integrations.registry.providers import IntegrationProvider
from app.core.integrations.registry.service import IntegrationRegistryService

__all__ = [
    "IntegrationCapability",
    "IntegrationInfo",
    "IntegrationProvider",
    "IntegrationRegistryService",
    "IntegrationStatus",
    "SyncSummary",
]
