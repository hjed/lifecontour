"""
Snipe-IT maintenance data transformer.

Converts Snipe-IT API maintenance responses into journal outbox event
payloads for the ``GEAR_MAINTENANCE`` journal type.  This is pure
transformation logic with no I/O or database access.

Maintenance type mapping (Snipe-IT → App):
- ``Maintenance`` → ``routine maintenance``
- ``Repair`` → ``repairing gear``
- ``PAT Test`` → ``routine inspection``
- ``Upgrade`` → ``routine maintenance``
- ``Hardware Support`` → ``repairing gear``
- ``Software Support`` → ``routine maintenance``
- Unknown / None → ``routine maintenance``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog

from snipeit_models import SnipeItMaintenance

logger = structlog.get_logger()

# Mapping from Snipe-IT maintenance type strings to VALID_MAINTENANCE_TYPES
_MAINTENANCE_TYPE_MAP: dict[str, str] = {
    "Maintenance": "routine maintenance",
    "Repair": "repairing gear",
    "PAT Test": "routine inspection",
    "Upgrade": "routine maintenance",
    "Hardware Support": "repairing gear",
    "Software Support": "routine maintenance",
}

_DEFAULT_MAINTENANCE_TYPE = "routine maintenance"

# Reverse mapping from app maintenance types to Snipe-IT maintenance type strings
_REVERSE_MAINTENANCE_TYPE_MAP: dict[str, str] = {
    "routine maintenance": "Maintenance",
    "repairing gear": "Repair",
    "routine inspection": "PAT Test",
}

_DEFAULT_SNIPEIT_MAINTENANCE_TYPE = "Maintenance"


@dataclass(frozen=True)
class MaintenanceTransformResult:
    """Result of transforming a Snipe-IT maintenance record.

    Attributes:
        journal_data: Journal payload for outbox events (title, content, dates, user_id).
        gear_maintenance_data: GEAR_MAINTENANCE type-specific data
            (gear_item_id, maintenance_type).
        snipeit_maintenance_id: Snipe-IT maintenance ID for ``SyncMetadata`` mapping.
        version_hash: SHA-256 hash of the maintenance data for change detection.
    """

    journal_data: dict[str, Any]
    gear_maintenance_data: dict[str, Any]
    snipeit_maintenance_id: int
    version_hash: str


class SnipeItMaintenanceTransformer:
    """Transforms Snipe-IT maintenance records into journal event payloads.

    All methods are stateless and can be called as static/classmethods.
    No I/O or database access is performed.
    """

    @staticmethod
    def transform(
        maintenance: SnipeItMaintenance,
        *,
        user_id: str,
        gear_item_id: str,
    ) -> MaintenanceTransformResult:
        """Transform a Snipe-IT maintenance record into journal event payloads.

        Args:
            maintenance: Snipe-IT API maintenance response.
            user_id: Internal user ID for the journal owner.
            gear_item_id: Internal gear item UUID string that the
                maintenance applies to.

        Returns:
            ``MaintenanceTransformResult`` containing journal data,
            gear maintenance data, and sync metadata.
        """
        # Map maintenance type
        maintenance_type = _map_maintenance_type(maintenance.asset_maintenance_type)

        # Title
        title = maintenance.title or _generate_fallback_title(maintenance_type)

        # Content from notes
        content = maintenance.notes or ""

        # Date range
        start_date = _parse_date(maintenance.start_date_str)
        end_date = _parse_date(maintenance.completion_date_str) or start_date

        # If no dates at all, fall back to now
        now = datetime.now(UTC)
        if start_date is None:
            start_dt = now
            end_dt = now
        else:
            start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
            end_dt = (
                datetime.combine(end_date, datetime.min.time(), tzinfo=UTC)
                if end_date
                else start_dt
            )

        # Version hash from maintenance data
        version_hash = hashlib.sha256(
            maintenance.model_dump_json().encode()
        ).hexdigest()

        journal_data: dict[str, Any] = {
            "user_id": user_id,
            "title": title,
            "content": content,
            "event_date_range_start": start_dt.isoformat(),
            "event_date_range_end": end_dt.isoformat(),
        }

        gear_maintenance_data: dict[str, Any] = {
            "gear_item_id": gear_item_id,
            "maintenance_type": maintenance_type,
        }

        return MaintenanceTransformResult(
            journal_data=journal_data,
            gear_maintenance_data=gear_maintenance_data,
            snipeit_maintenance_id=maintenance.id,
            version_hash=version_hash,
        )

    @staticmethod
    def reverse_transform(
        *,
        title: str,
        content: str,
        maintenance_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Transform app journal/maintenance data into a Snipe-IT API payload.

        This is the inverse of ``transform()``: converts local journal fields
        back into a dict suitable for ``POST /maintenances`` or
        ``PATCH /maintenances/{id}``.

        Args:
            title: Journal title.
            content: Journal content (becomes ``notes``).
            maintenance_type: App maintenance type string
                (e.g. ``routine maintenance``).
            start_date: Optional ISO date string ``YYYY-MM-DD``.
            end_date: Optional ISO date string ``YYYY-MM-DD``
                (becomes ``completion_date``).

        Returns:
            Dict of Snipe-IT API fields ready to be sent as JSON.
        """
        snipeit_type = _reverse_map_maintenance_type(maintenance_type)

        payload: dict[str, Any] = {
            "title": title,
            "notes": content,
            "asset_maintenance_type": snipeit_type,
        }

        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["completion_date"] = end_date

        return payload


def _map_maintenance_type(snipeit_type: str | None) -> str:
    """Map a Snipe-IT maintenance type string to app VALID_MAINTENANCE_TYPES.

    Returns the default type for unknown or None inputs with a warning log.
    """
    if snipeit_type is None:
        logger.warning(
            "Missing Snipe-IT maintenance type, defaulting",
            default=_DEFAULT_MAINTENANCE_TYPE,
        )
        return _DEFAULT_MAINTENANCE_TYPE

    mapped = _MAINTENANCE_TYPE_MAP.get(snipeit_type)
    if mapped is None:
        logger.warning(
            "Unknown Snipe-IT maintenance type, defaulting",
            snipeit_type=snipeit_type,
            default=_DEFAULT_MAINTENANCE_TYPE,
        )
        return _DEFAULT_MAINTENANCE_TYPE
    return mapped


def _reverse_map_maintenance_type(app_type: str) -> str:
    """Map an app maintenance type string back to a Snipe-IT type.

    Returns the default Snipe-IT type for unknown inputs with a warning log.
    """
    mapped = _REVERSE_MAINTENANCE_TYPE_MAP.get(app_type)
    if mapped is None:
        logger.warning(
            "Unknown app maintenance type for reverse mapping, defaulting",
            app_type=app_type,
            default=_DEFAULT_SNIPEIT_MAINTENANCE_TYPE,
        )
        return _DEFAULT_SNIPEIT_MAINTENANCE_TYPE
    return mapped


def _generate_fallback_title(maintenance_type: str) -> str:
    """Generate a descriptive fallback title when the Snipe-IT record has none."""
    return f"Gear maintenance: {maintenance_type}"


def _parse_date(date_str: str | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` date string, returning None on failure."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        logger.warning("Could not parse maintenance date", raw_value=date_str)
        return None
