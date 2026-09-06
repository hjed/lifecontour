"""Pydantic schemas for the user settings API.

Defines request/response shapes for ``GET`` and ``PUT /api/user-settings``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


def _validate_timezone(value: str) -> str:
    """Ensure the value is a known IANA timezone name."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"Unknown timezone: {value!r}") from err
    return value


class UserSettingsRequest(BaseModel):
    """Request body for updating user settings."""

    timezone: str = Field(
        ...,
        description="IANA timezone name, e.g. 'Australia/Sydney' or 'UTC'",
    )

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str) -> str:
        return _validate_timezone(value)


class UserSettingsAttributes(BaseModel):
    """Attributes for user settings.

    ``timezone`` is nullable, and ``null`` means the user has **not** chosen
    one — not that they chose UTC. The two have to stay distinguishable: the
    frontend anchors the day boundaries it writes on the configured zone and
    falls back to the browser's when there is none, so answering with the
    ``UTC`` default would silently move every unconfigured user's writes onto
    UTC midnight (issue #1401).
    """

    timezone: str | None = Field(
        ...,
        description="IANA timezone name, or null when the user has not set one",
    )


class UserSettingsData(BaseModel):
    """A single user-settings entry in JSON API format."""

    id: str
    type: str = "user_settings"
    attributes: UserSettingsAttributes


class UserSettingsResponse(BaseModel):
    """JSON API response for user settings."""

    data: UserSettingsData


UserSettingsResponse.model_rebuild()
