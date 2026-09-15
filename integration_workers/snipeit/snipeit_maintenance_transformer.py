"""
Snipe-IT maintenance data transformer.

Converts Snipe-IT API maintenance responses into journal outbox event
payloads for the ``GEAR_MAINTENANCE`` journal type.  This is pure
transformation logic with no I/O or database access.

Maintenance types map one-to-one (Snipe-IT ↔ App), so a record imported and
pushed back keeps its kind:
- ``Maintenance`` ↔ ``routine maintenance``
- ``Repair`` ↔ ``repairing gear``
- ``PAT Test`` ↔ ``routine inspection``
- ``Upgrade`` ↔ ``upgrading gear``
- ``Calibration`` ↔ ``calibration``
- ``Software Support`` ↔ ``software support``
- ``Hardware Support`` ↔ ``hardware support``
- ``Configuration Change`` ↔ ``configuration change``

Unknown / None Snipe-IT types import as ``routine maintenance``. ``retiring gear``
has no Snipe-IT equivalent and is pushed as ``Maintenance``.
"""

from __future__ import annotations

import hashlib
import html
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from core_shared.models.journals.constants import MaintenanceType

from snipeit_models import SnipeItMaintenance

logger = structlog.get_logger()

# Snipe-IT's maintenance kinds (en-US labels) and the app type each one is
_MAINTENANCE_TYPE_MAP: Mapping[str, MaintenanceType] = {
    "Maintenance": MaintenanceType.ROUTINE_MAINTENANCE,
    "Repair": MaintenanceType.REPAIRING_GEAR,
    "PAT Test": MaintenanceType.ROUTINE_INSPECTION,
    "Upgrade": MaintenanceType.UPGRADING_GEAR,
    "Calibration": MaintenanceType.CALIBRATION,
    "Software Support": MaintenanceType.SOFTWARE_SUPPORT,
    "Hardware Support": MaintenanceType.HARDWARE_SUPPORT,
    "Configuration Change": MaintenanceType.CONFIGURATION_CHANGE,
}

_DEFAULT_MAINTENANCE_TYPE = MaintenanceType.ROUTINE_MAINTENANCE

_DEFAULT_SNIPEIT_MAINTENANCE_TYPE = "Maintenance"

# Derived from the forward map so the two cannot disagree
_REVERSE_MAINTENANCE_TYPE_MAP: Mapping[MaintenanceType, str] = {
    **{
        app_type: snipeit_type
        for snipeit_type, app_type in _MAINTENANCE_TYPE_MAP.items()
    },
    MaintenanceType.RETIRING_GEAR: _DEFAULT_SNIPEIT_MAINTENANCE_TYPE,
}


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
        zone: str | None = None,
    ) -> MaintenanceTransformResult:
        """Transform a Snipe-IT maintenance record into journal event payloads.

        Args:
            maintenance: Snipe-IT API maintenance response.
            user_id: Internal user ID for the journal owner.
            gear_item_id: Internal gear item UUID string that the
                maintenance applies to.
            zone: IANA zone the journal owner's dates are read in, or ``None``
                for UTC. Snipe-IT dates are calendar dates, so each becomes the
                instant of its local midnight: the push reads them back in the
                same zone and sends the same dates.

        Returns:
            ``MaintenanceTransformResult`` containing journal data,
            gear maintenance data, and sync metadata.
        """
        # Map maintenance type
        maintenance_type = _map_maintenance_type(maintenance.asset_maintenance_type)

        # Snipe-IT HTML-escapes text on output but stores and accepts it raw,
        # so decode exactly once; ``reverse_transform`` sends the raw text back.
        title = (
            html.unescape(maintenance.title)
            if maintenance.title
            else _generate_fallback_title(maintenance_type)
        )
        content = html.unescape(maintenance.notes or "")

        # Date range
        start_date = _parse_date(maintenance.start_date_str)
        end_date = _parse_date(maintenance.completion_date_str) or start_date

        # If no dates at all, fall back to now
        now = datetime.now(UTC)
        if start_date is None:
            start_dt = now
            end_dt = now
        else:
            tz = ZoneInfo(zone) if zone else UTC
            start_dt = datetime.combine(
                start_date, datetime.min.time(), tzinfo=tz
            ).astimezone(UTC)
            end_dt = (
                datetime.combine(end_date, datetime.min.time(), tzinfo=tz).astimezone(
                    UTC
                )
                if end_date
                else start_dt
            )

        # Covers the mapped type and the anchoring zone as well as the record, so
        # an import stored under an older mapping or zone is synced again.
        version_hash = hashlib.sha256(
            f"{maintenance.model_dump_json()}\n{maintenance_type}\n{zone or 'UTC'}".encode()
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
            "name": title,
            "notes": content,
            "asset_maintenance_type": snipeit_type,
        }

        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["completion_date"] = end_date

        return payload

    @staticmethod
    def resolve_inbound_maintenance_type(
        snipeit_type: str | None, *, existing_type: str | None
    ) -> str:
        """Return the app type a re-import gives a journal that already exists.

        The app has a type Snipe-IT cannot record (``retiring gear``, pushed as
        ``Maintenance``). While the record still carries the kind the journal's
        type is pushed as, the journal keeps its type; any other kind means the
        record changed in Snipe-IT, so its mapped type wins.

        Args:
            snipeit_type: The record's ``asset_maintenance_type``.
            existing_type: The journal's current maintenance type, or ``None``
                when there is no journal yet.
        """
        if (
            snipeit_type is not None
            and existing_type is not None
            and _reverse_map_maintenance_type(existing_type) == snipeit_type
        ):
            return existing_type
        return _map_maintenance_type(snipeit_type)


def _map_maintenance_type(snipeit_type: str | None) -> str:
    """Map a Snipe-IT maintenance type string to app VALID_MAINTENANCE_TYPES.

    Returns the default type for unknown or None inputs with a warning log.
    """
    if snipeit_type is None:
        logger.warning(
            "Missing Snipe-IT maintenance type, defaulting",
            default=_DEFAULT_MAINTENANCE_TYPE.value,
        )
        return _DEFAULT_MAINTENANCE_TYPE.value

    mapped = _MAINTENANCE_TYPE_MAP.get(snipeit_type)
    if mapped is None:
        logger.warning(
            "Unknown Snipe-IT maintenance type, defaulting",
            snipeit_type=snipeit_type,
            default=_DEFAULT_MAINTENANCE_TYPE.value,
        )
        return _DEFAULT_MAINTENANCE_TYPE.value
    return mapped.value


def _reverse_map_maintenance_type(app_type: str) -> str:
    """Map an app maintenance type string back to a Snipe-IT type.

    Returns the default Snipe-IT type for unknown inputs with a warning log.
    """
    try:
        return _REVERSE_MAINTENANCE_TYPE_MAP[MaintenanceType(app_type)]
    except ValueError:
        logger.warning(
            "Unknown app maintenance type for reverse mapping, defaulting",
            app_type=app_type,
            default=_DEFAULT_SNIPEIT_MAINTENANCE_TYPE,
        )
        return _DEFAULT_SNIPEIT_MAINTENANCE_TYPE


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
