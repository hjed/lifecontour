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
def settings_service(mock_settings_repo):
    """Create a UserSettingsService instance."""
    return UserSettingsService(mock_settings_repo)


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
