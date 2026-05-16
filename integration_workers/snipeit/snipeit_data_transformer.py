"""
Snipe-IT asset data transformer.

Converts Snipe-IT API asset responses into ``GearItem`` domain entities
from ``core_shared``.  This is pure transformation logic with no I/O
or database access.

Field mapping (Snipe-IT → GearItem):
- ``name`` → ``name`` (fallback to ``asset_tag``)
- ``serial`` → ``serial_number``
- ``model.name`` → ``model``
- ``manufacturer.name`` → ``manufacturer``
- ``purchase_date.date`` → ``purchase_date`` (parsed to ``datetime.date``)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

import structlog
from core_shared.models.journals.constants import (
    MAX_GEAR_ITEM_FIELD_LENGTH,
    MAX_GEAR_ITEM_NAME_LENGTH,
)
from core_shared.models.journals.gear_item import GearItem

from snipeit_models import SnipeItAsset

logger = structlog.get_logger()


@dataclass(frozen=True)
class TransformResult:
    """Result of transforming a Snipe-IT asset.

    Wraps a ``GearItem`` entity together with Snipe-IT-specific metadata
    used for sync tracking (idempotency, change detection).

    Attributes:
        gear_item: The domain entity ready for persistence.
        snipeit_asset_id: Snipe-IT asset ID for ``SyncMetadata`` mapping.
        version_hash: SHA-256 hash of the asset data for change detection.
    """

    gear_item: GearItem
    snipeit_asset_id: int
    version_hash: str


class SnipeItDataTransformer:
    """Transforms Snipe-IT API asset data into ``GearItem`` entities.

    All methods are stateless and can be called as classmethods.
    No I/O or database access is performed.
    """

    @staticmethod
    def transform(asset: SnipeItAsset, *, user_id: str) -> TransformResult:
        """Transform a Snipe-IT asset into a ``GearItem`` entity.

        Args:
            asset: Snipe-IT API asset response.
            user_id: Internal user ID for the gear item owner.

        Returns:
            ``TransformResult`` containing the ``GearItem`` and sync metadata.
        """
        # Name: use asset name, fall back to asset_tag (asset_tag is required)
        raw_name = (
            asset.name.strip() if asset.name and asset.name.strip() else asset.asset_tag
        )
        name = raw_name[:MAX_GEAR_ITEM_NAME_LENGTH]

        # Serial number
        serial_number = _truncate(asset.serial, MAX_GEAR_ITEM_FIELD_LENGTH)

        # Model name from nested object
        model_name = _truncate(asset.model_name, MAX_GEAR_ITEM_FIELD_LENGTH)

        # Manufacturer name from nested object
        manufacturer_name = _truncate(
            asset.manufacturer_name, MAX_GEAR_ITEM_FIELD_LENGTH
        )

        # Purchase date parsing
        purchase_date_value = _parse_date(asset.purchase_date_str)

        # Version hash for change detection
        version_hash = hashlib.sha256(asset.model_dump_json().encode()).hexdigest()

        gear_item = GearItem(
            name=name,
            user_id=user_id,
            serial_number=serial_number,
            model=model_name,
            manufacturer=manufacturer_name,
            purchase_date=purchase_date_value,
        )

        return TransformResult(
            gear_item=gear_item,
            snipeit_asset_id=asset.id,
            version_hash=version_hash,
        )


def _truncate(value: str | None, max_length: int) -> str | None:
    """Truncate a string to ``max_length``, returning None for None input."""
    if value is None:
        return None
    return value[:max_length]


def _parse_date(date_str: str | None) -> date | None:
    """Parse a ``YYYY-MM-DD`` date string, returning None on failure."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        logger.warning("Could not parse purchase date", raw_value=date_str)
        return None
