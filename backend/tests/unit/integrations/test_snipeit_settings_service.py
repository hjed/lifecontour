"""Unit tests for SnipeItSettingsService."""

from unittest.mock import AsyncMock

import pytest

from app.core.integrations.models.snipeit import SnipeItSettings
from app.core.integrations.services.snipeit_settings_service import (
    SnipeItSettingsService,
)


@pytest.fixture
def mock_repo() -> AsyncMock:
    """Create a mock Snipe-IT settings repository."""
    return AsyncMock()


@pytest.fixture
def mock_transaction() -> AsyncMock:
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def service(mock_repo: AsyncMock) -> SnipeItSettingsService:
    """Create a SnipeItSettingsService instance."""
    return SnipeItSettingsService(mock_repo)


class TestSaveSettings:
    """Test the save_settings unit of work."""

    @pytest.mark.asyncio
    async def test_save_settings_persists_and_returns(
        self,
        service: SnipeItSettingsService,
        mock_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """save_settings upserts with a fresh candidate token and returns the saved entity."""
        settings = SnipeItSettings(user_id="user-1", base_url="https://snipe.example")
        saved = SnipeItSettings(user_id="user-1", base_url="https://snipe.example/")
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


class TestRotateWebhookToken:
    """Test the rotate_webhook_token unit of work."""

    @pytest.mark.asyncio
    async def test_rotate_stores_and_returns_a_new_token(
        self,
        service: SnipeItSettingsService,
        mock_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The generated token is stored for the user and returned."""
        mock_repo.set_webhook_token.return_value = True

        token = await service.rotate_webhook_token(
            user_id="user-1", transaction=mock_transaction
        )

        mock_repo.set_webhook_token.assert_awaited_once_with("user-1", token)
        assert token is not None
        assert len(token) == 43

    @pytest.mark.asyncio
    async def test_rotate_returns_none_without_settings(
        self,
        service: SnipeItSettingsService,
        mock_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A user with no Snipe-IT settings has no token to rotate."""
        mock_repo.set_webhook_token.return_value = False

        token = await service.rotate_webhook_token(
            user_id="user-1", transaction=mock_transaction
        )

        assert token is None
