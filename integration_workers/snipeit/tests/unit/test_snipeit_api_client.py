# ruff: noqa: E402
"""Tests for Snipe-IT API client."""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}/personal_management_test"
    )
os.environ["ENCRYPTION_KEY"] = "testkey"

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError, _parse_retry_after
from snipeit_models import SnipeItAsset, SnipeItAssetListResponse
from snipeit_rate_limiter import SnipeItRateLimitError


@pytest.fixture
def mock_refresh() -> AsyncMock:
    """Async callback returning a new token string."""
    return AsyncMock(return_value="new-token")


@pytest_asyncio.fixture
async def client_no_refresh() -> AsyncGenerator[SnipeItAPIClient, None]:
    """Client without a refresh callback (uses real httpx.AsyncClient)."""
    client = SnipeItAPIClient.create(
        base_url="https://snipeit.example.com",
        access_token="test-token",
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def client_with_refresh(
    mock_refresh: AsyncMock,
) -> AsyncGenerator[SnipeItAPIClient, None]:
    """Client with a refresh callback."""
    client = SnipeItAPIClient.create(
        base_url="https://snipeit.example.com",
        access_token="test-token",
        on_token_refresh=mock_refresh,
    )
    yield client
    await client.close()


def _asset_json(asset_id: int = 1, name: str = "Test") -> dict[str, object]:
    """Minimal asset JSON for mocking."""
    return {
        "id": asset_id,
        "name": name,
        "asset_tag": f"TAG-{asset_id:03d}",
    }


def _list_json(
    assets: list[dict[str, object]] | None = None, total: int | None = None
) -> dict[str, object]:
    """Asset list response JSON for mocking."""
    rows = assets or [_asset_json()]
    return {"total": total if total is not None else len(rows), "rows": rows}


def _ok_response(json_data: object) -> MagicMock:
    """Create a mock 200 response with JSON body."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.headers = {}
    return resp


class TestSnipeItAPIClientListAssets:
    """Tests for list_assets method."""

    @pytest.mark.asyncio
    async def test_successful_list_fetch(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Successful GET hardware returns parsed asset list."""
        resp = _ok_response(
            _list_json([_asset_json(1, "Rope"), _asset_json(2, "Harness")], total=2)
        )
        with patch.object(client_no_refresh._client, "get", return_value=resp):
            result = await client_no_refresh.list_assets()

        assert isinstance(result, SnipeItAssetListResponse)
        assert result.total == 2
        assert len(result.rows) == 2
        assert result.rows[0].name == "Rope"

    @pytest.mark.asyncio
    async def test_pagination_params_passed(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Pagination parameters are forwarded to the API call."""
        resp = _ok_response(_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_assets(page=3, per_page=50)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        assert params["offset"] == 100  # (page-1) * per_page = 2*50
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_assigned_to_filter(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Assigned-to user filter is passed as query parameter."""
        resp = _ok_response(_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_assets(assigned_to_user_id="42")

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        assert params["assigned_to"] == "42"

    @pytest.mark.asyncio
    async def test_paths_do_not_have_leading_slash(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """API paths must not start with / to preserve httpx base_url prefix."""
        resp = _ok_response(_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_assets()

        path = mock_get.call_args.args[0]
        assert not path.startswith("/"), f"Path should not start with /: {path}"


class TestSnipeItAPIClientGetAsset:
    """Tests for get_asset method."""

    @pytest.mark.asyncio
    async def test_successful_get(self, client_no_refresh: SnipeItAPIClient) -> None:
        """GET hardware/{id} returns parsed asset."""
        resp = _ok_response(_asset_json(42, "Climbing Rope"))
        with patch.object(client_no_refresh._client, "get", return_value=resp):
            result = await client_no_refresh.get_asset(42)

        assert isinstance(result, SnipeItAsset)
        assert result.id == 42
        assert result.name == "Climbing Rope"

    @pytest.mark.asyncio
    async def test_get_asset_path_has_no_leading_slash(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """get_asset uses relative path without leading /."""
        resp = _ok_response(_asset_json(42))
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.get_asset(42)

        path = mock_get.call_args.args[0]
        assert path == "hardware/42"


class TestSnipeItAPIClientErrorHandling:
    """Tests for error handling in the API client."""

    @pytest.mark.asyncio
    async def test_401_triggers_retry_callback(
        self,
        client_with_refresh: SnipeItAPIClient,
        mock_refresh: AsyncMock,
    ) -> None:
        """401 response invokes on_token_refresh callback and retries."""
        mock_401 = MagicMock()
        mock_401.status_code = 401

        mock_ok = _ok_response(_asset_json(1, "After Refresh"))

        with patch.object(
            client_with_refresh._client, "get", side_effect=[mock_401, mock_ok]
        ):
            result = await client_with_refresh.get_asset(1)

        mock_refresh.assert_called_once()
        assert result.name == "After Refresh"

    @pytest.mark.asyncio
    async def test_401_without_callback_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """401 without refresh callback raises SnipeItAPIError."""
        mock_401 = MagicMock()
        mock_401.status_code = 401
        with patch.object(client_no_refresh._client, "get", return_value=mock_401):
            with pytest.raises(SnipeItAPIError, match="authentication failed"):
                await client_no_refresh.get_asset(1)

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """429 response raises SnipeItRateLimitError."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "30"}
        with patch.object(client_no_refresh._client, "get", return_value=mock_429):
            with pytest.raises(SnipeItRateLimitError, match="rate limited"):
                await client_no_refresh.get_asset(1)

    @pytest.mark.asyncio
    async def test_5xx_raises_api_error(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """5xx response raises SnipeItAPIError."""
        mock_500 = MagicMock()
        mock_500.status_code = 500
        with patch.object(client_no_refresh._client, "get", return_value=mock_500):
            with pytest.raises(SnipeItAPIError, match="500"):
                await client_no_refresh.get_asset(1)

    @pytest.mark.asyncio
    async def test_4xx_raises_api_error(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Non-retryable 4xx raises SnipeItAPIError."""
        mock_404 = MagicMock()
        mock_404.status_code = 404
        with patch.object(client_no_refresh._client, "get", return_value=mock_404):
            with pytest.raises(SnipeItAPIError, match="404"):
                await client_no_refresh.get_asset(1)

    @pytest.mark.asyncio
    async def test_connection_error_is_raised(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Connection errors propagate for upstream retry."""
        with patch.object(
            client_no_refresh._client,
            "get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(httpx.ConnectError):
                await client_no_refresh.get_asset(1)


class TestSnipeItAPIClientClose:
    """Tests for client cleanup."""

    @pytest.mark.asyncio
    async def test_close(self, client_no_refresh: SnipeItAPIClient) -> None:
        """close() calls aclose on the httpx client."""
        with patch.object(client_no_refresh._client, "aclose") as mock_close:
            await client_no_refresh.close()
            mock_close.assert_called_once()


class TestParseRetryAfter:
    """Tests for _parse_retry_after helper."""

    def test_numeric_string(self) -> None:
        """Integer string parses to float."""
        assert _parse_retry_after("30") == 30.0

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert _parse_retry_after(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert _parse_retry_after("") is None

    def test_non_numeric_returns_none(self) -> None:
        """Non-numeric string (e.g. HTTP-date) returns None gracefully."""
        assert _parse_retry_after("Thu, 01 Jan 2026 00:00:00 GMT") is None
