"""
Domain models for the pluggable integration registry.

These models represent integration metadata that is returned by
``IntegrationProvider`` implementations and aggregated by
``IntegrationRegistryService``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class IntegrationStatus(StrEnum):
    """Connection status of an integration."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    TOKEN_EXPIRED = "token_expired"


class IntegrationCapability(StrEnum):
    """Capabilities that an integration can declare."""

    CONTACTS_SYNC = "contacts_sync"
    CALENDAR_SYNC = "calendar_sync"
    ACTIVITY_IMPORT = "activity_import"


@dataclass(frozen=True)
class SyncSummary:
    """Summary of recent sync activity for an integration."""

    last_sync_time: datetime | None = None
    sync_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class IntegrationInfo:
    """
    Complete metadata for a single registered integration.

    Returned by ``IntegrationProvider.get_integration_info`` and aggregated
    into the ``GET /api/integrations`` response.
    """

    id: str
    name: str
    status: IntegrationStatus
    capabilities: list[IntegrationCapability] = field(default_factory=list)
    sync_summary: SyncSummary = field(default_factory=SyncSummary)
    needs_reauth: bool = False
    needs_reconsent: bool = False
