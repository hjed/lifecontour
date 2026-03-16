"""Unit tests for per-calendar sync token save/load helpers.

Tests the _save_calendar_sync_token and _load_calendar_sync_token functions
that store tokens per-calendar in the calendar_sync_tokens table.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest


class TestSaveCalendarSyncToken:
    """Tests for _save_calendar_sync_token helper."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_save_upserts_with_calendar_id(self, mock_session: AsyncMock) -> None:
        """Save should UPSERT into calendar_sync_tokens keyed by calendar_id."""
        from worker import _save_calendar_sync_token

        await _save_calendar_sync_token(
            mock_session, "token-123", "user-1", "test@example.com", "cal-work"
        )

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["sync_token"] == "token-123"
        assert params["user_id"] == "user-1"
        assert params["email"] == "test@example.com"
        assert params["google_calendar_id"] == "cal-work"

    @pytest.mark.asyncio
    async def test_save_defaults_to_primary_calendar(
        self, mock_session: AsyncMock
    ) -> None:
        """When no calendar_id is given, should default to 'primary'."""
        from worker import _save_calendar_sync_token

        await _save_calendar_sync_token(
            mock_session, "token-456", "user-1", "test@example.com"
        )

        params = mock_session.execute.call_args[0][1]
        assert params["google_calendar_id"] == "primary"

    @pytest.mark.asyncio
    async def test_save_sets_last_synced_at(self, mock_session: AsyncMock) -> None:
        """Save should set last_synced_at to current time."""
        from worker import _save_calendar_sync_token

        await _save_calendar_sync_token(
            mock_session, "token-789", "user-1", "test@example.com", "cal-1"
        )

        params = mock_session.execute.call_args[0][1]
        assert params["now"] is not None

    @pytest.mark.asyncio
    async def test_save_converts_user_id_to_string(
        self, mock_session: AsyncMock
    ) -> None:
        """Save should convert integer user_id to string."""
        from worker import _save_calendar_sync_token

        await _save_calendar_sync_token(
            mock_session, "token-abc", 42, "test@example.com", "cal-1"
        )

        params = mock_session.execute.call_args[0][1]
        assert params["user_id"] == "42"

    @pytest.mark.asyncio
    async def test_save_targets_calendar_sync_tokens_table(
        self, mock_session: AsyncMock
    ) -> None:
        """SQL should reference calendar_sync_tokens table, not user_google_integration."""
        from worker import _save_calendar_sync_token

        await _save_calendar_sync_token(
            mock_session, "token-xyz", "user-1", "test@example.com", "cal-1"
        )

        stmt = mock_session.execute.call_args[0][0]
        sql_text = str(stmt)
        assert "calendar_sync_tokens" in sql_text
        assert "user_google_integration" not in sql_text


class TestLoadCalendarSyncToken:
    """Tests for _load_calendar_sync_token helper."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_load_returns_token_when_found(
        self, mock_session: AsyncMock
    ) -> None:
        """Should return the sync token when one exists."""
        from worker import _load_calendar_sync_token

        result_mock = MagicMock()
        result_mock.scalar.return_value = "existing-token-123"
        mock_session.execute.return_value = result_mock

        token = await _load_calendar_sync_token(
            mock_session, "user-1", "test@example.com", "cal-work"
        )

        assert token == "existing-token-123"

    @pytest.mark.asyncio
    async def test_load_returns_none_when_no_token(
        self, mock_session: AsyncMock
    ) -> None:
        """Should return None when no token exists for this calendar."""
        from worker import _load_calendar_sync_token

        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        mock_session.execute.return_value = result_mock

        token = await _load_calendar_sync_token(
            mock_session, "user-1", "test@example.com", "nonexistent-cal"
        )

        assert token is None

    @pytest.mark.asyncio
    async def test_load_queries_by_calendar_id(
        self, mock_session: AsyncMock
    ) -> None:
        """Load should query by the specific calendar_id, not just user/account."""
        from worker import _load_calendar_sync_token

        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        mock_session.execute.return_value = result_mock

        await _load_calendar_sync_token(
            mock_session, "user-1", "test@example.com", "specific-calendar"
        )

        params = mock_session.execute.call_args[0][1]
        assert params["google_calendar_id"] == "specific-calendar"

    @pytest.mark.asyncio
    async def test_load_defaults_to_primary_calendar(
        self, mock_session: AsyncMock
    ) -> None:
        """When no calendar_id is given, should default to 'primary'."""
        from worker import _load_calendar_sync_token

        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        mock_session.execute.return_value = result_mock

        await _load_calendar_sync_token(
            mock_session, "user-1", "test@example.com"
        )

        params = mock_session.execute.call_args[0][1]
        assert params["google_calendar_id"] == "primary"

    @pytest.mark.asyncio
    async def test_load_targets_calendar_sync_tokens_table(
        self, mock_session: AsyncMock
    ) -> None:
        """SQL should query calendar_sync_tokens table."""
        from worker import _load_calendar_sync_token

        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        mock_session.execute.return_value = result_mock

        await _load_calendar_sync_token(
            mock_session, "user-1", "test@example.com", "cal-1"
        )

        stmt = mock_session.execute.call_args[0][0]
        sql_text = str(stmt)
        assert "calendar_sync_tokens" in sql_text
