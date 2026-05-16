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
