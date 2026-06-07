"""Integration tests for SqlUserSettingsRepository."""

import pytest

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings

pytestmark = pytest.mark.integration


@pytest.fixture
def user_settings_repo(async_connection):
    """Provide a SqlUserSettingsRepository using the test connection."""
    return SqlUserSettingsRepository(async_connection)


class TestSqlUserSettingsRepository:
    @pytest.mark.asyncio
    async def test_get_by_user_id_returns_none_when_empty(self, user_settings_repo):
        assert await user_settings_repo.get_by_user_id("nobody") is None

    @pytest.mark.asyncio
    async def test_save_creates_then_updates(self, user_settings_repo):
        created = await user_settings_repo.save(
            UserSettings(user_id="u1", timezone="Australia/Sydney")
        )
        assert created.timezone == "Australia/Sydney"
        assert created.created_at is not None

        updated = await user_settings_repo.save(
            UserSettings(user_id="u1", timezone="America/New_York")
        )
        assert updated.timezone == "America/New_York"

        fetched = await user_settings_repo.get_by_user_id("u1")
        assert fetched is not None
        assert fetched.timezone == "America/New_York"

    @pytest.mark.asyncio
    async def test_get_timezone_falls_back_to_utc(self, user_settings_repo):
        assert await user_settings_repo.get_timezone("missing") == "UTC"

    @pytest.mark.asyncio
    async def test_get_timezone_returns_stored(self, user_settings_repo):
        await user_settings_repo.save(
            UserSettings(user_id="u2", timezone="Europe/London")
        )
        assert await user_settings_repo.get_timezone("u2") == "Europe/London"

    @pytest.mark.asyncio
    async def test_get_default_timezone_when_empty(self, user_settings_repo):
        assert await user_settings_repo.get_default_timezone() == "UTC"

    @pytest.mark.asyncio
    async def test_get_default_timezone_returns_latest(self, user_settings_repo):
        await user_settings_repo.save(
            UserSettings(user_id="solo", timezone="Pacific/Auckland")
        )
        assert await user_settings_repo.get_default_timezone() == "Pacific/Auckland"
