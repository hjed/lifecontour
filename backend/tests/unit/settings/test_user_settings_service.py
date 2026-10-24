"""Unit tests for UserSettingsService."""

from unittest.mock import AsyncMock

import pytest

from app.core.settings.models import UserSettings, UserSettingsChanges
from app.core.settings.services.user_settings_service import UserSettingsService


@pytest.fixture
def mock_settings_repo():
    """Create a mock user settings repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def mock_contacts_reimport():
    """Create a mock for forcing a full contacts re-import."""
    return AsyncMock()


@pytest.fixture
def settings_service(mock_settings_repo, mock_contacts_reimport):
    """Create a UserSettingsService instance."""
    return UserSettingsService(mock_settings_repo, mock_contacts_reimport)


class TestUpdateSettings:
    """Test the update_settings unit of work."""

    @pytest.mark.asyncio
    async def test_update_settings_passes_the_changes_and_returns(
        self, settings_service, mock_settings_repo, mock_transaction
    ) -> None:
        """update_settings writes only the given changes and returns the row."""
        saved = UserSettings(user_id="user-1", default_country="NZ")
        mock_settings_repo.update.return_value = saved
        changes = UserSettingsChanges(default_country="NZ")

        result = await settings_service.update_settings(
            user_id="user-1",
            changes=changes,
            transaction=mock_transaction,
        )

        assert result is saved
        mock_settings_repo.update.assert_awaited_once_with("user-1", changes)

    @pytest.mark.asyncio
    async def test_a_sent_default_country_forces_a_contacts_re_import(
        self, settings_service, mock_contacts_reimport, mock_transaction
    ) -> None:
        """Even an unchanged one: the save is the recovery for a missed sync."""
        await settings_service.update_settings(
            user_id="user-1",
            changes=UserSettingsChanges(default_country="NZ"),
            transaction=mock_transaction,
        )

        mock_contacts_reimport.force_full_contacts_sync.assert_awaited_once_with(
            "user-1"
        )

    @pytest.mark.asyncio
    async def test_a_timezone_change_leaves_the_contacts_alone(
        self, settings_service, mock_contacts_reimport, mock_transaction
    ) -> None:
        await settings_service.update_settings(
            user_id="user-1",
            changes=UserSettingsChanges(timezone="Europe/London"),
            transaction=mock_transaction,
        )

        mock_contacts_reimport.force_full_contacts_sync.assert_not_awaited()
