"""
Pydantic response models for Snipe-IT API v1.

These models parse JSON responses from the Snipe-IT REST API into typed
objects used by ``SnipeItAPIClient``. Field names mirror Snipe-IT's API
naming conventions.

Snipe-IT returns nested ``{id, name}`` objects for related entities
(model, manufacturer, status_label, etc.).  We parse those into
``SnipeItNestedObject`` and expose convenience properties on
``SnipeItAsset`` for flat access.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SnipeItNestedObject(BaseModel):
    """A nested ``{id, name}`` object commonly returned by Snipe-IT.

    Used for model, manufacturer, status_label, category, location, etc.
    """

    id: int | None = None
    name: str | None = None


class SnipeItDateObject(BaseModel):
    """A Snipe-IT date field with ``date`` and ``formatted`` sub-keys.

    Snipe-IT returns dates like ``{"date": "2024-01-15", "formatted": "..."}``
    or ``{"datetime": "...", "formatted": "..."}`` for timestamp fields.
    """

    date: str | None = Field(default=None, alias="date")
    datetime: str | None = None
    formatted: str | None = None


class SnipeItAssignedTo(BaseModel):
    """The ``assigned_to`` object from a Snipe-IT hardware response.

    Snipe-IT returns this when an asset is checked out to a user, asset,
    or location.  The ``type`` field discriminates between them.
    """

    id: int
    name: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    type: str  # "user", "asset", or "location"


class SnipeItAsset(BaseModel):
    """A single Snipe-IT asset (hardware item).

    Corresponds to responses from ``GET /api/v1/hardware/{id}`` and
    individual rows from ``GET /api/v1/hardware``.

    See: https://snipe-it.readme.io/reference/hardware
    """

    id: int
    name: str | None = None
    asset_tag: str
    serial: str | None = None
    model: SnipeItNestedObject | None = None
    model_number: str | None = None
    manufacturer: SnipeItNestedObject | None = None
    status_label: SnipeItNestedObject | None = None
    category: SnipeItNestedObject | None = None
    location: SnipeItNestedObject | None = None
    purchase_date: SnipeItDateObject | None = None
    purchase_cost: str | None = None
    notes: str | None = None
    assigned_to: SnipeItAssignedTo | None = None
    updated_at: SnipeItDateObject | None = None

    # -- Convenience accessors ------------------------------------------------

    @property
    def model_name(self) -> str | None:
        """Return the model name from the nested object."""
        return self.model.name if self.model else None

    @property
    def manufacturer_name(self) -> str | None:
        """Return the manufacturer name from the nested object."""
        return self.manufacturer.name if self.manufacturer else None

    @property
    def purchase_date_str(self) -> str | None:
        """Return the raw purchase date string (``YYYY-MM-DD``)."""
        return self.purchase_date.date if self.purchase_date else None


class SnipeItAssetListResponse(BaseModel):
    """Paginated response from ``GET /api/v1/hardware``.

    Snipe-IT wraps the list in ``{"total": N, "rows": [...]}``.
    """

    total: int
    rows: list[SnipeItAsset] = Field(default_factory=list)


class _SnipeItMaintenanceBase(BaseModel):
    """Shared fields for Snipe-IT maintenance response models.

    Both GET and POST/PATCH response shapes share these fields.
    Not intended for direct instantiation.
    """

    id: int
    title: str | None = None
    asset_maintenance_type: str | None = None
    start_date: SnipeItDateObject | None = None
    completion_date: SnipeItDateObject | None = None
    notes: str | None = None
    cost: str | None = None
    supplier: SnipeItNestedObject | None = None
    updated_at: SnipeItDateObject | None = None

    # -- Convenience accessors ------------------------------------------------

    @property
    def start_date_str(self) -> str | None:
        """Return the raw start date string (``YYYY-MM-DD``)."""
        return self.start_date.date if self.start_date else None

    @property
    def completion_date_str(self) -> str | None:
        """Return the raw completion date string (``YYYY-MM-DD``)."""
        return self.completion_date.date if self.completion_date else None


class SnipeItMaintenance(_SnipeItMaintenanceBase):
    """A Snipe-IT maintenance record from a GET response.

    Corresponds to responses from ``GET /api/v1/maintenances/{id}`` and
    individual rows from ``GET /api/v1/maintenances``.

    GET responses return the associated asset as a nested ``{id, name}``
    object and do **not** include a top-level ``asset_id`` field.  Use
    the ``asset_id`` property to access the asset's numeric ID.

    See: https://snipe-it.readme.io/reference/maintenances
    """

    asset: SnipeItNestedObject | None = None

    @property
    def asset_id(self) -> int | None:
        """Return the asset's numeric ID from the nested ``asset`` object."""
        return self.asset.id if self.asset else None


class SnipeItMaintenanceWriteResponse(_SnipeItMaintenanceBase):
    """A Snipe-IT maintenance record from a POST/PATCH ``payload`` response.

    Snipe-IT wraps mutating responses as
    ``{"status": "success", "payload": {...}}``.
    The ``payload`` object includes ``asset_id`` as a top-level int
    and does **not** include a nested ``asset`` object.
    """

    asset_id: int


class SnipeItMaintenanceListResponse(BaseModel):
    """Paginated response from ``GET /api/v1/maintenances``.

    Snipe-IT wraps the list in ``{"total": N, "rows": [...]}``.
    """

    total: int
    rows: list[SnipeItMaintenance] = Field(default_factory=list)
