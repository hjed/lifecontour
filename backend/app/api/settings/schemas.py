"""Pydantic schemas for the user settings API.

Defines request/response shapes for ``GET`` and ``PATCH /api/user-settings``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core_shared.models.contacts.value_objects import CountryCode
from pydantic import BaseModel, Field, field_validator

from app.core.settings.models import UNSET, UserSettingsChanges


def _validate_timezone(value: str) -> str:
    """Ensure the value is a known IANA timezone name."""
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"Unknown timezone: {value!r}") from err
    return value


class UserSettingsRequest(BaseModel):
    """Request body for a partial update of user settings.

    A field the body omits is left as it is. ``default_country: null`` clears
    the country; the timezone can be changed but not cleared.
    """

    timezone: str | None = Field(
        default=None,
        description="IANA timezone name, e.g. 'Australia/Sydney' or 'UTC'",
    )
    default_country: str | None = Field(
        default=None,
        description=(
            "ISO 3166-1 alpha-2 country, e.g. 'AU', used for imported addresses "
            "with no country; null clears it"
        ),
    )

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_valid(cls, value: str | None) -> str:
        # Runs only on a value the body sent, so None here is an explicit null.
        if value is None:
            raise ValueError("The timezone can be changed but not cleared")
        return _validate_timezone(value)

    @field_validator("default_country")
    @classmethod
    def default_country_must_be_alpha_2(cls, value: str | None) -> str | None:
        if value is not None:
            CountryCode(value)
        return value

    def to_changes(self) -> UserSettingsChanges:
        """The settings changes this body asks for, omitted fields unset."""
        return UserSettingsChanges(
            timezone=self.timezone if self.timezone is not None else UNSET,
            default_country=(
                self.default_country
                if "default_country" in self.model_fields_set
                else UNSET
            ),
        )


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
    default_country: str | None = Field(
        default=None,
        description="ISO 3166-1 alpha-2 country, or null when the user has not set one",
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
