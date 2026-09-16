"""Unit tests for SnipeItSettingsService."""

from unittest.mock import AsyncMock

import pytest

from app.core.integrations.services.snipeit_settings_service import (
    SnipeItSettingsService,
)


@pytest.fixture
def mock_repo():
    """Create a mock Snipe-IT settings repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def service(mock_repo):
    """Create a SnipeItSettingsService instance."""
    return SnipeItSettingsService(mock_repo)


class TestSaveSettings:
    """Test the save_settings unit of work."""

    @pytest.mark.asyncio
    async def test_save_settings_persists_and_returns(
        self, service, mock_repo, mock_transaction
    ):
        """save_settings upserts with a fresh candidate token and returns the saved entity."""
        settings = object()
        saved = object()
        mock_repo.save.return_value = saved

        result = await service.save_settings(
            settings=settings, transaction=mock_transaction
        )

        assert result is saved
        mock_repo.save.assert_awaited_once()
        assert mock_repo.save.call_args.args == (settings,)
        new_webhook_token = mock_repo.save.call_args.kwargs["new_webhook_token"]
        assert isinstance(new_webhook_token, str)
        assert len(new_webhook_token) == 43
