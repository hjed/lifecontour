"""Unit tests for the user settings request schema."""

import pytest
from pydantic import ValidationError

from app.api.settings.schemas import UserSettingsRequest
from app.core.settings.models import UNSET, ThemePalette


class TestThemePalette:
    """The colour palette a user picks; ``null`` returns to the default."""

    @pytest.mark.parametrize("value", ["default", "emerald"])
    def test_accepts_a_known_palette(self, value: str) -> None:
        request = UserSettingsRequest.model_validate({"theme_palette": value})

        assert request.to_changes().theme_palette == ThemePalette(value)

    @pytest.mark.parametrize("value", ["Emerald", "rainbow", ""])
    def test_rejects_an_unknown_palette(self, value: str) -> None:
        with pytest.raises(ValidationError):
            UserSettingsRequest.model_validate({"theme_palette": value})

    def test_null_clears_the_palette(self) -> None:
        request = UserSettingsRequest.model_validate({"theme_palette": None})

        assert request.to_changes().theme_palette is None

    def test_an_omitted_palette_is_left_as_it_is(self) -> None:
        request = UserSettingsRequest.model_validate({"timezone": "UTC"})

        assert request.to_changes().theme_palette is UNSET

    def test_a_palette_alone_leaves_the_other_settings_unset(self) -> None:
        changes = UserSettingsRequest.model_validate(
            {"theme_palette": "emerald"}
        ).to_changes()

        assert changes.timezone is UNSET
        assert changes.default_country is UNSET
