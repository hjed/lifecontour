"""Integration tests for SqlUserSettingsRepository."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings, UserSettingsChanges

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
    async def test_update_country_alone_creates_a_row_without_a_timezone(
        self, user_settings_repo: SqlUserSettingsRepository
    ) -> None:
        saved = await user_settings_repo.update(
            "u3", UserSettingsChanges(default_country="NZ")
        )

        assert saved.timezone is None
        assert saved.default_country == "NZ"
        assert await user_settings_repo.get_timezone("u3") == "UTC"

    @pytest.mark.asyncio
    async def test_update_writes_only_the_fields_it_names(
        self, user_settings_repo: SqlUserSettingsRepository
    ) -> None:
        await user_settings_repo.update(
            "u4",
            UserSettingsChanges(timezone="Europe/London", default_country="GB"),
        )

        kept_country = await user_settings_repo.update(
            "u4", UserSettingsChanges(timezone="Europe/Paris")
        )
        assert kept_country.default_country == "GB"

        cleared = await user_settings_repo.update(
            "u4", UserSettingsChanges(default_country=None)
        )
        assert cleared.timezone == "Europe/Paris"
        assert cleared.default_country is None

    @pytest.mark.asyncio
    async def test_a_null_timezone_reads_as_none(
        self,
        user_settings_repo: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ) -> None:
        """NULL is "not chosen", never the string ``"None"``."""
        await async_connection.execute(
            text("INSERT INTO user_settings (user_id) VALUES ('u5')")
        )

        fetched = await user_settings_repo.get_by_user_id("u5")

        assert fetched is not None
        assert fetched.timezone is None
        assert await user_settings_repo.get_timezone("u5") == "UTC"
