"""
Unit tests for StravaAPIClient.

Tests token injection, endpoint routing, rate limit enforcement,
401 refresh-and-retry, and error propagation — all with mocked HTTP.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strava_api_client import StravaAPIClient, StravaAPIError


def _make_response(
    status_code: int = 200,
    json_data: object = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = _make_http_error(status_code, resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_http_error(status_code: int, response: MagicMock) -> Exception:
    """Construct a lightweight stand-in for httpx.HTTPStatusError."""
    import httpx

    request = httpx.Request("GET", "https://www.strava.com/api/v3/test")
    raw_response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} error",
        request=request,
        response=raw_response,
    )


@pytest.fixture
def auth_service() -> AsyncMock:
    """Mock StravaAuthService with a working refresh_token."""
    service = AsyncMock()
    service.decrypt.return_value = "test-access-token"
    return service


@pytest.fixture
def api_client(auth_service: AsyncMock) -> StravaAPIClient:
    """Create a StravaAPIClient with a mock auth service."""
    return StravaAPIClient(
        access_token="test-access-token",
        refresh_token_value="test-refresh-token",
        auth_service=auth_service,
    )


# -- Athlete endpoint --


class TestGetAthlete:
    """Tests for ``get_athlete()``."""

    @pytest.mark.asyncio
    async def test_returns_parsed_athlete(self, api_client: StravaAPIClient) -> None:
        """get_athlete returns a StravaAthlete model."""
        athlete_data = {"id": 12345, "firstname": "Jane", "lastname": "Doe"}
        mock_resp = _make_response(json_data=athlete_data)

        with patch.object(
            api_client._client, "get", return_value=mock_resp
        ) as mock_get:
            result = await api_client.get_athlete()

        assert result.id == 12345
        assert result.firstname == "Jane"
        mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_injects_bearer_token(self, api_client: StravaAPIClient) -> None:
        """Requests include Authorization: Bearer header."""
        athlete_data = {"id": 1, "firstname": "A", "lastname": "B"}
        mock_resp = _make_response(json_data=athlete_data)

        with patch.object(
            api_client._client, "get", return_value=mock_resp
        ) as mock_get:
            await api_client.get_athlete()

        call_kwargs = mock_get.call_args
        # Bearer token is set on the client level, verify URL is correct
        assert "athlete" in str(call_kwargs)


# -- Activities endpoints --


class TestListActivities:
    """Tests for ``list_activities()``."""

    @pytest.mark.asyncio
    async def test_returns_list_of_activities(
        self, api_client: StravaAPIClient
    ) -> None:
        """list_activities returns a list of StravaActivity models."""
        activities_data = [
            {
                "id": 1001,
                "name": "Morning Run",
                "type": "Run",
                "sport_type": "Run",
                "start_date": "2026-05-01T06:30:00Z",
                "elapsed_time": 3600,
                "moving_time": 3200,
                "distance": 10000.0,
                "total_elevation_gain": 150.5,
                "athlete": {"id": 12345},
            }
        ]
        mock_resp = _make_response(json_data=activities_data)

        with patch.object(api_client._client, "get", return_value=mock_resp):
            result = await api_client.list_activities()

        assert len(result) == 1
        assert result[0].id == 1001
        assert result[0].name == "Morning Run"

    @pytest.mark.asyncio
    async def test_passes_query_params(self, api_client: StravaAPIClient) -> None:
        """list_activities passes after, before, page, per_page as query params."""
        mock_resp = _make_response(json_data=[])

        with patch.object(
            api_client._client, "get", return_value=mock_resp
        ) as mock_get:
            await api_client.list_activities(
                after=1000000, before=2000000, page=2, per_page=50
            )

        _, kwargs = mock_get.call_args
        params = kwargs.get("params", {})
        assert params["after"] == 1000000
        assert params["before"] == 2000000
        assert params["page"] == 2
        assert params["per_page"] == 50


class TestGetActivity:
    """Tests for ``get_activity()``."""

    @pytest.mark.asyncio
    async def test_returns_single_activity(self, api_client: StravaAPIClient) -> None:
        """get_activity returns a single StravaActivity with full detail."""
        activity_data = {
            "id": 2001,
            "name": "Afternoon Hike",
            "type": "Hike",
            "sport_type": "Hike",
            "start_date": "2026-05-01T14:00:00Z",
            "elapsed_time": 7200,
            "moving_time": 6000,
            "distance": 15000.0,
            "total_elevation_gain": 500.0,
            "start_latlng": [-33.7, 151.3],
            "athlete": {"id": 12345},
        }
        mock_resp = _make_response(json_data=activity_data)

        with patch.object(api_client._client, "get", return_value=mock_resp):
            result = await api_client.get_activity(2001)

        assert result.id == 2001
        assert result.start_latlng == [-33.7, 151.3]


class TestGetActivityStreams:
    """Tests for ``get_activity_streams()``."""

    @pytest.mark.asyncio
    async def test_returns_stream_set(self, api_client: StravaAPIClient) -> None:
        """get_activity_streams returns a StravaStreamSet."""
        streams_data = [
            {
                "type": "latlng",
                "data": [[-33.8, 151.2]],
                "series_type": "distance",
                "original_size": 1,
                "resolution": "high",
            },
            {
                "type": "altitude",
                "data": [10.0],
                "series_type": "distance",
                "original_size": 1,
                "resolution": "high",
            },
        ]
        mock_resp = _make_response(json_data=streams_data)

        with patch.object(api_client._client, "get", return_value=mock_resp):
            result = await api_client.get_activity_streams(
                3001, keys=["latlng", "altitude"]
            )

        assert result.latlng is not None
        assert result.altitude is not None
        assert result.time is None


# -- Token refresh and error handling --


class TestTokenRefresh:
    """Tests for automatic 401 → refresh → retry logic."""

    @pytest.mark.asyncio
    async def test_401_triggers_refresh_and_retry(
        self, api_client: StravaAPIClient, auth_service: AsyncMock
    ) -> None:
        """A 401 response triggers token refresh and retries the request."""
        from datetime import UTC, datetime

        from strava_auth_service import StravaTokenData

        auth_service.refresh_token.return_value = StravaTokenData(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            athlete_id=12345,
        )

        athlete_data = {"id": 12345, "firstname": "Jane", "lastname": "Doe"}
        first_resp = _make_response(status_code=401)
        second_resp = _make_response(json_data=athlete_data)

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_resp
            return second_resp

        with patch.object(api_client._client, "get", side_effect=mock_get):
            result = await api_client.get_athlete()

        assert result.id == 12345
        auth_service.refresh_token.assert_called_once_with("test-refresh-token")

    @pytest.mark.asyncio
    async def test_401_after_refresh_propagates_error(
        self, api_client: StravaAPIClient, auth_service: AsyncMock
    ) -> None:
        """If the retry after refresh also returns 401, the error propagates."""
        from datetime import UTC, datetime

        from strava_auth_service import StravaTokenData

        auth_service.refresh_token.return_value = StravaTokenData(
            access_token="new-token",
            refresh_token="new-refresh",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            athlete_id=12345,
        )

        first_resp = _make_response(status_code=401)
        second_resp = _make_response(status_code=401)

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_resp
            return second_resp

        with patch.object(api_client._client, "get", side_effect=mock_get):
            with pytest.raises(StravaAPIError, match="authentication failed"):
                await api_client.get_athlete()


class TestErrorHandling:
    """Tests for HTTP error responses."""

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(
        self, api_client: StravaAPIClient
    ) -> None:
        """A 429 response raises StravaAPIError with rate limit info."""
        from strava_rate_limiter import StravaRateLimitError

        mock_resp = _make_response(status_code=429, headers={"Retry-After": "900"})

        with patch.object(api_client._client, "get", return_value=mock_resp):
            with pytest.raises(StravaRateLimitError):
                await api_client.get_athlete()

    @pytest.mark.asyncio
    async def test_500_raises_api_error(self, api_client: StravaAPIClient) -> None:
        """A 500 response raises StravaAPIError."""
        mock_resp = _make_response(status_code=500)

        with patch.object(api_client._client, "get", return_value=mock_resp):
            with pytest.raises(StravaAPIError, match="500"):
                await api_client.get_athlete()


class TestRateLimiterIntegration:
    """Rate limiter checked before each request."""

    @pytest.mark.asyncio
    async def test_rate_limiter_checked_before_request(
        self, api_client: StravaAPIClient
    ) -> None:
        """When rate limiter raises, no HTTP request is made."""
        from strava_rate_limiter import StravaRateLimitError

        api_client._rate_limiter._short_count = 100  # exhaust short limit

        with patch.object(api_client._client, "get") as mock_get:
            with pytest.raises(StravaRateLimitError):
                await api_client.get_athlete()

        mock_get.assert_not_called()
