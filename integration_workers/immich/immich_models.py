"""
Pydantic response models for the Immich REST API.

These models represent the JSON responses from Immich's API endpoints.
Only fields relevant to the Personal Management System integration are
included; ``model_config`` is set to ignore extra fields so new Immich
API additions don't break deserialization.

Immich uses camelCase in its JSON responses, so we use Pydantic's
``alias_generator`` to map from camelCase to snake_case Python fields.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _ImmichBase(BaseModel):
    """Shared model config for all Immich response models.

    - ``alias_generator=to_camel``: deserialise camelCase JSON keys
    - ``populate_by_name=True``: allow both ``birth_date`` and ``birthDate``
    - ``extra="ignore"``: tolerate unknown fields from newer API versions
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class ImmichServerInfo(_ImmichBase):
    """Response from ``GET /server/about``."""

    version: str
    """Immich server version string (e.g. ``"v1.106.4"``)."""

    licensed: bool = False


class ImmichPerson(_ImmichBase):
    """Response from ``GET /people/{id}`` or element in ``GET /people``."""

    id: str
    """UUID of the person."""

    name: str = ""
    """Display name (may be empty for unnamed faces)."""

    birth_date: str | None = None
    """ISO-8601 date string (``YYYY-MM-DD``) or ``None``."""

    thumbnail_path: str = ""
    """Server-relative thumbnail path."""

    is_hidden: bool = False
    """Whether the person is hidden in the Immich UI."""


class ImmichPeopleResponse(_ImmichBase):
    """Response from ``GET /people``."""

    people: list[ImmichPerson]
    total: int = 0
    hidden: int = 0
    has_next_page: bool = False


class ImmichExifInfo(_ImmichBase):
    """Exif metadata embedded in an ``ImmichAsset``."""

    date_time_original: datetime | None = None
    """Original capture datetime from EXIF."""

    timezone: str | None = None
    """IANA timezone from EXIF (e.g. ``"Australia/Sydney"``)."""


class ImmichAssetPerson(_ImmichBase):
    """Person tag on an asset (face detection result)."""

    id: str
    name: str = ""


class ImmichAsset(_ImmichBase):
    """Response from asset-level endpoints or album asset lists."""

    id: str
    """UUID of the asset."""

    type: str = "IMAGE"
    """Asset type (``IMAGE`` or ``VIDEO``)."""

    original_file_name: str = ""
    """Original filename of the uploaded media."""

    taken_at: datetime | None = None
    """When the photo/video was taken (UTC)."""

    people: list[ImmichAssetPerson] = []
    """People detected in this asset."""

    exif_info: ImmichExifInfo | None = None
    """EXIF metadata, if available."""


class ImmichAlbum(_ImmichBase):
    """Response from ``GET /albums/{id}`` or element in ``GET /albums``."""

    id: str
    """UUID of the album."""

    album_name: str = ""
    """Album title."""

    description: str = ""
    """Album description."""

    album_thumbnail_asset_id: str | None = None
    """UUID of the cover photo asset, or ``None``."""

    asset_count: int = 0
    """Number of assets in the album."""

    assets: list[ImmichAsset] = []
    """Full asset list (populated when fetching a single album)."""

    updated_at: datetime | None = None
    """Last update timestamp."""

    shared: bool = False
    """Whether the album is shared."""


class ImmichSharedLink(_ImmichBase):
    """Response from ``GET /shared-links`` or ``POST /shared-links``."""

    id: str
    """UUID of the shared link."""

    key: str
    """URL key for the shared link."""

    type: str = "ALBUM"
    """Link type (``ALBUM`` or ``INDIVIDUAL``)."""

    created_at: datetime | None = None
    """When the shared link was created."""

    description: str | None = None
    """Optional description."""

    album: ImmichAlbum | None = None
    """Linked album, if type is ALBUM."""

    assets: list[ImmichAsset] = []
    """Linked assets, if type is INDIVIDUAL."""

    password: str | None = None
    """Optional password protection."""

    expires_at: datetime | None = None
    """Expiration datetime, if set."""

    allow_download: bool = True
    """Whether downloads are permitted."""

    allow_upload: bool = False
    """Whether uploads are permitted."""
