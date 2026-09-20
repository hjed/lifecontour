"""Unit tests for webhook channel helpers (watch_events, stop_channel, setup_calendar_webhook).

Tests GoogleAPIClient.watch_events/stop_channel methods and the
setup_calendar_webhook ARQ task.
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from core_shared.testing import make_arq_ctx, make_mock_redis
from googleapiclient.errors import HttpError

sys.path.insert(0, "/core_shared")


def make_http_error(status: int, reason: str = "Error") -> HttpError:
    """Build a googleapiclient HttpError carrying the given HTTP status."""
    response = MagicMock()
    type(response).status = PropertyMock(return_value=status)
    response.reason = reason
    return HttpError(resp=response, content=reason.encode())


class TestWatchEvents:
    """Tests for GoogleAPIClient.watch_events method."""

    @pytest.fixture
    def mock_service(self) -> MagicMock:
        service = MagicMock()
        watch_mock = MagicMock()
        watch_mock.execute.return_value = {
            "kind": "api#channel",
            "id": "channel-uuid-123",
            "resourceId": "resource-id-456",
            "expiration": "1711580400000",  # Some future timestamp
        }
        events_mock = MagicMock()
        events_mock.watch.return_value = watch_mock
        service.events.return_value = events_mock
        return service

    @pytest.mark.asyncio
    async def test_watch_events_calls_events_watch(
        self, mock_service: MagicMock
    ) -> None:
        """Should call events().watch() with correct parameters."""
        from google_client import GoogleAPIClient

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        result = await client.watch_events(
            calendar_id="cal-123",
            channel_id="channel-uuid",
            webhook_url="https://example.com/webhook",
        )

        assert result is not None
        mock_service.events().watch.assert_called_once()
        call_kwargs = mock_service.events().watch.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body"))
        assert body["id"] == "channel-uuid"
        assert body["type"] == "web_hook"
        assert body["address"] == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_watch_events_returns_api_response(
        self, mock_service: MagicMock
    ) -> None:
        """Should return the full Google API response."""
        from google_client import GoogleAPIClient

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        result = await client.watch_events(
            calendar_id="cal-123",
            channel_id="channel-uuid",
            webhook_url="https://example.com/webhook",
        )

        assert result["resourceId"] == "resource-id-456"
        assert result["id"] == "channel-uuid-123"


class TestStopChannel:
    """Tests for GoogleAPIClient.stop_channel method."""

    @pytest.fixture
    def mock_service(self) -> MagicMock:
        service = MagicMock()
        stop_mock = MagicMock()
        stop_mock.execute.return_value = None
        channels_mock = MagicMock()
        channels_mock.stop.return_value = stop_mock
        service.channels.return_value = channels_mock
        return service

    @pytest.mark.asyncio
    async def test_stop_channel_calls_channels_stop(
        self, mock_service: MagicMock
    ) -> None:
        """Should call channels().stop() with channel_id and resourceId."""
        from google_client import GoogleAPIClient

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        await client.stop_channel("channel-uuid", "resource-id-456")

        mock_service.channels().stop.assert_called_once()
        call_kwargs = mock_service.channels().stop.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body"))
        assert body["id"] == "channel-uuid"
        assert body["resourceId"] == "resource-id-456"

    @pytest.mark.asyncio
    async def test_stop_channel_treats_404_as_already_stopped(
        self, mock_service: MagicMock
    ) -> None:
        """A channel Google has already forgotten is not an error to stop."""
        from google_client import GoogleAPIClient

        mock_service.channels().stop().execute.side_effect = make_http_error(
            404, "Not Found"
        )

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        await client.stop_channel("channel-uuid", "resource-id-456")

        # The request was attempted and its 404 swallowed — asserting this
        # keeps the test honest, since it would otherwise also pass if
        # stop_channel skipped the call altogether.
        mock_service.channels().stop().execute.assert_called()

    @pytest.mark.asyncio
    async def test_stop_channel_treats_410_as_already_stopped(
        self, mock_service: MagicMock
    ) -> None:
        """A channel reported as gone is likewise already in the desired state."""
        from google_client import GoogleAPIClient

        mock_service.channels().stop().execute.side_effect = make_http_error(
            410, "Gone"
        )

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        await client.stop_channel("channel-uuid", "resource-id-456")

        mock_service.channels().stop().execute.assert_called()

    @pytest.mark.asyncio
    async def test_stop_channel_reraises_other_http_errors(
        self, mock_service: MagicMock
    ) -> None:
        """A genuine failure to stop the channel still propagates."""
        from google_client import GoogleAPIClient

        mock_service.channels().stop().execute.side_effect = make_http_error(
            500, "Internal Server Error"
        )

        client = GoogleAPIClient.__new__(GoogleAPIClient)
        client._get_calendar_service = AsyncMock(return_value=mock_service)

        with pytest.raises(HttpError):
            await client.stop_channel("channel-uuid", "resource-id-456")


def patch_watch_repo(*active_channels: Any) -> tuple[Any, Any]:
    """Patch CalendarWatchRepository, reporting ``active_channels`` as recorded.

    Returns the repo mock and the patcher, so tests can assert on the calls the
    task makes through it (lock, lookup, stale-row cleanup).
    """
    repo = MagicMock()
    repo.lock_calendar = AsyncMock()
    repo.get_active_channels = AsyncMock(return_value=list(active_channels))
    repo.clear_channels_for_other_accounts = AsyncMock()
    return repo, patch("worker.CalendarWatchRepository", MagicMock(return_value=repo))


def make_active_channel(
    google_account_email: str = "test@example.com",
    channel_id: str = "old-channel-id",
    channel_resource_id: str = "old-resource-id",
    channel_expiration: datetime | None = None,
) -> Any:
    """Build an ActiveCalendarChannel as the repository would return one."""
    from core_shared.repositories import ActiveCalendarChannel

    return ActiveCalendarChannel(
        google_account_email=google_account_email,
        channel_id=channel_id,
        channel_resource_id=channel_resource_id,
        channel_expiration=channel_expiration,
    )


class TestSetupCalendarWebhook:
    """Tests for the setup_calendar_webhook ARQ task."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session: AsyncMock) -> MagicMock:
        factory = MagicMock()
        factory.return_value = mock_session
        return factory

    @pytest.fixture
    def mock_ctx(self, mock_session_factory: MagicMock) -> dict[str, Any]:
        return make_arq_ctx(
            session_factory=mock_session_factory, redis=make_mock_redis()
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_webhook_base_url(self, mock_ctx: dict) -> None:
        """Should return skipped status when webhook_base_url is empty."""
        from worker import setup_calendar_webhook

        with patch("worker.settings") as mock_settings:
            mock_settings.webhook_base_url = ""

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_registers_watch_and_persists_channel(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Should call watch_events and persist channel metadata."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={
                "resourceId": "res-id-789",
                "expiration": "1711580400000",
            }
        )

        _, repo_patch = patch_watch_repo()

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        assert result["resource_id"] == "res-id-789"
        mock_client.watch_events.assert_called_once()
        # Only the UPSERT runs on the session now; reading the existing
        # channel moved to CalendarWatchRepository.
        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_existing_channel_if_exists(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Should stop existing channel if one is registered in the database."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={
                "resourceId": "res-id-123",
                "expiration": "1711580400000",
            }
        )
        mock_client.stop_channel = AsyncMock()

        _, repo_patch = patch_watch_repo(
            make_active_channel(
                channel_expiration=datetime.now(UTC) + timedelta(days=3)
            )
        )

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        mock_client.stop_channel.assert_called_once_with(
            channel_id="old-channel-id", resource_id="old-resource-id"
        )
        mock_client.watch_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_constructs_webhook_url_correctly(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Should construct webhook URL from webhook_base_url + endpoint path."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={
                "resourceId": "res-id",
                "expiration": "1711580400000",
            }
        )

        _, repo_patch = patch_watch_repo()

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://my-app.example.com/"

            await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        webhook_url = mock_client.watch_events.call_args.kwargs["webhook_url"]
        assert (
            webhook_url
            == "https://my-app.example.com/api/integrations/google/calendar/webhook"
        )

    @pytest.mark.asyncio
    async def test_handles_watch_api_error(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Should return error status when Google API watch fails."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(side_effect=Exception("API Error"))

        _, repo_patch = patch_watch_repo()

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "error"
        assert "API Error" in result["error"]

    @pytest.mark.asyncio
    async def test_skips_stop_for_expired_channel(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """An expired channel is already gone, so do not ask Google to stop it."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={
                "resourceId": "res-id-123",
                "expiration": "1711580400000",
            }
        )
        mock_client.stop_channel = AsyncMock()

        _, repo_patch = patch_watch_repo(
            make_active_channel(
                channel_id="expired-channel-id",
                channel_resource_id="expired-resource-id",
                channel_expiration=datetime.now(UTC) - timedelta(days=1),
            )
        )

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        mock_client.stop_channel.assert_not_called()
        mock_client.watch_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_stops_channel_with_unknown_expiration(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Without a recorded expiry the channel may still be live, so stop it."""
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={
                "resourceId": "res-id-123",
                "expiration": "1711580400000",
            }
        )
        mock_client.stop_channel = AsyncMock()

        _, repo_patch = patch_watch_repo(make_active_channel(channel_expiration=None))

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        mock_client.stop_channel.assert_called_once_with(
            channel_id="old-channel-id", resource_id="old-resource-id"
        )

    @pytest.mark.asyncio
    async def test_locks_the_calendar_before_reading_its_channel(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """Setup serialises on the calendar so two runs cannot both register.

        The lock is taken before the existing channel is read, so a run that
        waits for it sees whatever the previous holder committed.
        """
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={"resourceId": "res-id", "expiration": "1711580400000"}
        )

        repo, repo_patch = patch_watch_repo()

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        # Keyed by the calendar alone: the account differs between callers, so
        # including it would hand concurrent runs different locks.
        repo.lock_calendar.assert_awaited_once_with(
            user_id="user-1",
            google_calendar_id="cal-1",
        )

    @pytest.mark.asyncio
    async def test_stops_a_channel_held_by_another_account(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """A channel registered under the user's other account is still replaced.

        Looking it up per account would miss it, so setup would open a second
        channel and leave the first live — Google then delivers on both.
        """
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={"resourceId": "res-id", "expiration": "1711580400000"}
        )
        mock_client.stop_channel = AsyncMock()

        repo, repo_patch = patch_watch_repo(
            make_active_channel(
                google_account_email="other@example.com",
                channel_expiration=datetime.now(UTC) + timedelta(days=3),
            )
        )

        with (
            patch("worker.settings") as mock_settings,
            patch(
                "worker._create_google_client", return_value=mock_client
            ) as make_client,
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        mock_client.stop_channel.assert_awaited_once()
        # The stop must use the account that registered the channel, since
        # another account's token cannot address it.
        assert make_client.call_args_list[-1].args[2] == "other@example.com"

    @pytest.mark.asyncio
    async def test_clears_the_channel_left_on_another_accounts_row(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """The superseded row must not keep claiming a channel.

        calendar_sync_tokens is keyed by (user, account, calendar), so a
        different account inserts a new row instead of replacing the old; the
        renewal sweep would otherwise keep finding the dead channel.
        """
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={"resourceId": "res-id", "expiration": "1711580400000"}
        )

        repo, repo_patch = patch_watch_repo()

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        repo.clear_channels_for_other_accounts.assert_awaited_once_with(
            "user-1", "cal-1", "test@example.com"
        )

    @pytest.mark.asyncio
    async def test_stops_every_recorded_channel_before_clearing_them(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """All recorded channels are stopped, not just the newest.

        Registrations made before the lookup went account-agnostic can leave a
        row per account. Clearing the ones we did not stop would leave them
        live at Google with no metadata, so their notifications are rejected as
        unknown until they expire.
        """
        from worker import setup_calendar_webhook

        mock_client = MagicMock()
        mock_client.watch_events = AsyncMock(
            return_value={"resourceId": "res-id", "expiration": "1711580400000"}
        )
        mock_client.stop_channel = AsyncMock()

        future = datetime.now(UTC) + timedelta(days=3)
        _, repo_patch = patch_watch_repo(
            make_active_channel(
                google_account_email="a@example.com",
                channel_id="chan-a",
                channel_resource_id="res-a",
                channel_expiration=future,
            ),
            make_active_channel(
                google_account_email="b@example.com",
                channel_id="chan-b",
                channel_resource_id="res-b",
                channel_expiration=future,
            ),
        )

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", return_value=mock_client),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "test@example.com", "user-1", "cal-1"
            )

        assert result["status"] == "success"
        stopped = {
            call.kwargs["channel_id"]
            for call in mock_client.stop_channel.call_args_list
        }
        assert stopped == {"chan-a", "chan-b"}

    @pytest.mark.asyncio
    async def test_registers_even_when_the_old_channels_account_is_gone(
        self, mock_ctx: dict, mock_session: AsyncMock
    ) -> None:
        """A disconnected previous owner must not block re-registration.

        Renewal falls back to a connected account when the channel's owner has
        been disconnected, so setup then tries to stop that channel with
        credentials that no longer exist. Loading them raises, and swallowing it
        is what lets the calendar be registered under the working account
        instead of failing every sweep.
        """
        from google_auth_service import GoogleAuthTokensNotFoundError
        from worker import setup_calendar_webhook

        working_client = MagicMock()
        working_client.watch_events = AsyncMock(
            return_value={"resourceId": "res-id", "expiration": "1711580400000"}
        )
        gone_client = MagicMock()
        gone_client.stop_channel = AsyncMock(
            side_effect=GoogleAuthTokensNotFoundError("no tokens for gone@example.com")
        )

        repo, repo_patch = patch_watch_repo(
            make_active_channel(
                google_account_email="gone@example.com",
                channel_expiration=datetime.now(UTC) + timedelta(days=3),
            )
        )

        def client_for(_session: Any, _user: Any, email: str) -> MagicMock:
            return gone_client if email == "gone@example.com" else working_client

        with (
            patch("worker.settings") as mock_settings,
            patch("worker._create_google_client", side_effect=client_for),
            repo_patch,
        ):
            mock_settings.webhook_base_url = "https://example.com"

            result = await setup_calendar_webhook(
                mock_ctx, "live@example.com", "user-1", "cal-1"
            )

        # The stop failed, but the replacement was still registered and the
        # stale row still cleared.
        assert result["status"] == "success"
        gone_client.stop_channel.assert_awaited_once()
        working_client.watch_events.assert_called_once()
        repo.clear_channels_for_other_accounts.assert_awaited_once()
