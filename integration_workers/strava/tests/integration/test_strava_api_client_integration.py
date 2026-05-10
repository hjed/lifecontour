"""
Integration tests for StravaAPIClient with mocked HTTP responses.

These tests use ``httpx``'s transport-level mocking to simulate real
Strava API responses — including rate limit headers, error codes, and
multi-step flows like 401 → refresh → retry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from strava_api_client import StravaAPIClient, StravaAPIError
from strava_auth_service import StravaTokenData
from strava_rate_limiter import StravaRateLimitError


def _strava_athlete_json() -> dict[str, Any]:
    """Realistic Strava athlete response fixture."""
    return {
        "id": 12345,
        "firstname": "Jane",
        "lastname": "Doe",
        "profile": "https://dgalywyr863hv.cloudfront.net/pictures/athletes/12345.jpg",
        "city": "Sydney",
        "state": "New South Wales",
        "country": "Australia",
    }


def _strava_activity_json(activity_id: int = 9876543210) -> dict[str, Any]:
    """Realistic Strava activity detail response fixture."""
    return {
        "id": activity_id,
        "name": "Blue Mountains Bushwalk",
        "description": "Grand Canyon Track loop",
        "type": "Hike",
        "sport_type": "Hike",
        "start_date": "2026-05-01T08:30:00Z",
        "elapsed_time": 18000,
        "moving_time": 14400,
        "distance": 12500.0,
        "total_elevation_gain": 650.0,
        "calories": 1200.0,
        "average_heartrate": 130.0,
        "max_heartrate": 165.0,
        "start_latlng": [-33.6839, 150.3110],
        "end_latlng": [-33.6839, 150.3110],
        "athlete": {"id": 12345},
    }


def _strava_streams_json() -> dict[str, Any]:
    """Realistic Strava activity streams response fixture (key_by_type=true)."""
    return {
        "latlng": {
            "type": "latlng",
            "data": [[-33.6839, 150.3110], [-33.6840, 150.3112], [-33.6842, 150.3115]],
            "series_type": "distance",
            "original_size": 3,
            "resolution": "high",
        },
        "altitude": {
            "type": "altitude",
            "data": [800.0, 810.5, 795.0],
            "series_type": "distance",
            "original_size": 3,
            "resolution": "high",
        },
        "time": {
            "type": "time",
            "data": [0, 60, 120],
            "series_type": "distance",
            "original_size": 3,
            "resolution": "high",
        },
    }


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns pre-configured responses by URL pattern."""

    def __init__(self) -> None:
        self.responses: list[tuple[str, int, object, dict[str, str]]] = []
        self._call_index: int = 0

    def add_response(
        self,
        url_pattern: str,
        status_code: int = 200,
        json_data: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue a response that matches a URL substring."""
        self.responses.append((url_pattern, status_code, json_data, headers or {}))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return the next queued response matching the URL."""
        url = str(request.url)
        for i, (pattern, status, data, hdrs) in enumerate(self.responses):
            if pattern in url:
                self.responses.pop(i)
                import json as json_mod

                content = json_mod.dumps(data).encode() if data is not None else b""
                return httpx.Response(
                    status_code=status,
                    content=content,
                    headers={**hdrs, "content-type": "application/json"},
                    request=request,
                )
        raise ValueError(f"No mock response configured for {url}")


@pytest.fixture
def mock_auth_service() -> AsyncMock:
    """Mock auth service for token refresh integration tests."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_transport() -> MockTransport:
    """Create a MockTransport for httpx."""
    return MockTransport()


@pytest.fixture
def integration_client(
    mock_auth_service: AsyncMock, mock_transport: MockTransport
) -> StravaAPIClient:
    """Create a StravaAPIClient using the mock transport."""
    client = StravaAPIClient(
        access_token="test-access-token",
        refresh_token_value="test-refresh-token",
        auth_service=mock_auth_service,
    )
    # Replace the internal httpx client with our mock transport
    client._client = httpx.AsyncClient(
        transport=mock_transport,
        base_url="https://www.strava.com/api/v3/",
        headers={"Authorization": "Bearer test-access-token"},
    )
    return client


class TestGetAthleteIntegration:
    """Integration: ``GET /athlete`` with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_get_athlete_returns_parsed_model(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """Full roundtrip: HTTP response → StravaAthlete model."""
        mock_transport.add_response(
            "/athlete",
            json_data=_strava_athlete_json(),
            headers={"X-RateLimit-Usage": "1,1", "X-RateLimit-Limit": "100,1000"},
        )

        athlete = await integration_client.get_athlete()

        assert athlete.id == 12345
        assert athlete.firstname == "Jane"
        assert athlete.lastname == "Doe"
        assert athlete.city == "Sydney"


class TestListActivitiesIntegration:
    """Integration: ``GET /athlete/activities`` with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_list_activities_returns_parsed_models(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """Full roundtrip: HTTP response → list[StravaActivity]."""
        mock_transport.add_response(
            "/athlete/activities",
            json_data=[_strava_activity_json()],
            headers={"X-RateLimit-Usage": "2,2", "X-RateLimit-Limit": "100,1000"},
        )

        activities = await integration_client.list_activities()

        assert len(activities) == 1
        assert activities[0].id == 9876543210
        assert activities[0].name == "Blue Mountains Bushwalk"
        assert activities[0].type == "Hike"


class TestGetActivityIntegration:
    """Integration: ``GET /activities/{id}`` with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_get_activity_with_start_latlng(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """Full roundtrip: HTTP response → StravaActivity with GPS data."""
        mock_transport.add_response(
            "/activities/9876543210",
            json_data=_strava_activity_json(),
            headers={"X-RateLimit-Usage": "3,3", "X-RateLimit-Limit": "100,1000"},
        )

        activity = await integration_client.get_activity(9876543210)

        assert activity.start_latlng == [-33.6839, 150.3110]
        assert activity.total_elevation_gain == 650.0
        assert activity.average_heartrate == 130.0


class TestGetActivityStreamsIntegration:
    """Integration: ``GET /activities/{id}/streams`` with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_get_streams_returns_stream_set(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """Full roundtrip: HTTP response → StravaStreamSet."""
        mock_transport.add_response(
            "/activities/9876543210/streams",
            json_data=_strava_streams_json(),
            headers={"X-RateLimit-Usage": "4,4", "X-RateLimit-Limit": "100,1000"},
        )

        stream_set = await integration_client.get_activity_streams(
            9876543210, keys=["latlng", "altitude", "time"]
        )

        assert stream_set.latlng is not None
        assert len(stream_set.latlng.data) == 3
        assert stream_set.altitude is not None
        assert stream_set.altitude.data == [800.0, 810.5, 795.0]
        assert stream_set.time is not None
        assert stream_set.time.data == [0, 60, 120]


class TestErrorResponsesIntegration:
    """Integration: error responses via mocked HTTP."""

    @pytest.mark.asyncio
    async def test_401_triggers_refresh_flow(
        self,
        integration_client: StravaAPIClient,
        mock_transport: MockTransport,
        mock_auth_service: AsyncMock,
    ) -> None:
        """401 → refresh token → retry with new token → success."""
        mock_auth_service.refresh_token.return_value = StravaTokenData(
            access_token="refreshed-token",
            refresh_token="refreshed-refresh",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
            athlete_id=12345,
        )

        # First call returns 401, second returns success
        mock_transport.add_response("/athlete", status_code=401)
        mock_transport.add_response("/athlete", json_data=_strava_athlete_json())

        athlete = await integration_client.get_athlete()

        assert athlete.id == 12345
        mock_auth_service.refresh_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """429 response raises an error."""
        mock_transport.add_response(
            "/athlete",
            status_code=429,
            headers={"Retry-After": "900"},
        )

        with pytest.raises(StravaRateLimitError):
            await integration_client.get_athlete()

    @pytest.mark.asyncio
    async def test_500_raises_api_error(
        self, integration_client: StravaAPIClient, mock_transport: MockTransport
    ) -> None:
        """500 response raises StravaAPIError."""
        mock_transport.add_response("/athlete", status_code=500)

        with pytest.raises(StravaAPIError):
            await integration_client.get_athlete()
