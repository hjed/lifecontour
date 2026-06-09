"""Unit tests for UserSettingsService."""

from unittest.mock import AsyncMock

import pytest

from app.core.settings.models import UserSettings
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


class TestSaveSettings:
    """Test the save_settings unit of work."""

    @pytest.mark.asyncio
    async def test_save_settings_persists_and_returns(
        self, settings_service, mock_settings_repo, mock_transaction
    ):
        """save_settings upserts via the repo and returns the saved entity."""
        saved = UserSettings(user_id="user-1", timezone="Australia/Sydney")
        mock_settings_repo.save.return_value = saved

        result = await settings_service.save_settings(
            user_id="user-1",
            timezone="Australia/Sydney",
            transaction=mock_transaction,
        )

        assert result is saved
        mock_settings_repo.save.assert_called_once()
        persisted = mock_settings_repo.save.call_args.args[0]
        assert persisted.user_id == "user-1"
        assert persisted.timezone == "Australia/Sydney"
