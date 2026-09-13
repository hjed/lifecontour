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
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError, _parse_retry_after
from snipeit_models import (
    SnipeItActivityListResponse,
    SnipeItAsset,
    SnipeItAssetListResponse,
    SnipeItMaintenance,
    SnipeItMaintenanceListResponse,
    SnipeItMaintenanceWriteResponse,
)
from snipeit_rate_limiter import SnipeItRateLimitError


class TestSnipeItAPIClientListAssetActivity:
    """Tests for list_asset_activity method."""

    @pytest.mark.asyncio
    async def test_filters_the_asset_activity_report(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """The activity report is filtered to one asset and action, newest first."""
        resp = _ok_response({"total": 0, "rows": []})
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_asset_activity(
                42, action_type="checkin from", page=2, per_page=50
            )

        assert mock_get.call_args.args[0] == "reports/activity"
        assert mock_get.call_args.kwargs["params"] == {
            "item_type": "asset",
            "item_id": 42,
            "action_type": "checkin from",
            "sort": "id",
            "order": "desc",
            "offset": 50,
            "limit": 50,
        }

    @pytest.mark.asyncio
    async def test_parses_activity_rows(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        resp = _ok_response(
            {
                "total": 1,
                "rows": [
                    {
                        "id": 277,
                        "action_type": "checkout",
                        "action_date": {
                            "datetime": "2019-05-01 00:00:00",
                            "formatted": "01/05/2019 12:00 AM",
                        },
                        "item": {"id": 42, "name": "Tent", "type": "asset"},
                        "target": {"id": 5, "name": "Harry", "type": "user"},
                    }
                ],
            }
        )
        with patch.object(client_no_refresh._client, "get", return_value=resp):
            result = await client_no_refresh.list_asset_activity(
                42, action_type="checkout"
            )

        assert isinstance(result, SnipeItActivityListResponse)
        assert result.total == 1
        (row,) = result.rows
        assert row.id == 277
        assert row.action_day == "2019-05-01"


@pytest_asyncio.fixture
async def client_no_refresh() -> AsyncGenerator[SnipeItAPIClient, None]:
    """Client for testing (uses real httpx.AsyncClient)."""
    client = SnipeItAPIClient.create(
        base_url="https://snipeit.example.com",
        api_key="test-api-key",
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


def _maintenance_json(
    maintenance_id: int = 1, asset_id: int = 10, title: str = "Inspection"
) -> dict[str, object]:
    """Minimal maintenance JSON for mocking.

    POST/PATCH responses include ``asset_id``; GET responses use a nested
    ``asset`` object instead.  This helper produces the POST/PATCH shape
    (explicit ``asset_id``).  Use ``_maintenance_get_json`` for GET.
    """
    return {
        "id": maintenance_id,
        "asset_id": asset_id,
        "title": title,
    }


def _maintenance_get_json(
    maintenance_id: int = 1, asset_id: int = 10, title: str = "Inspection"
) -> dict[str, object]:
    """Maintenance JSON matching real Snipe-IT GET response format.

    GET responses include a nested ``asset`` object instead of a
    top-level ``asset_id``.
    """
    return {
        "id": maintenance_id,
        "asset": {"id": asset_id, "name": f"Asset-{asset_id}"},
        "title": title,
    }


def _maintenance_list_json(
    maintenances: list[dict[str, object]] | None = None, total: int | None = None
) -> dict[str, object]:
    """Maintenance list response JSON for mocking."""
    rows = maintenances or [_maintenance_get_json()]
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


class TestSnipeItAPIClientUpdateAsset:
    """Tests for update_asset method."""

    @pytest.mark.asyncio
    async def test_successful_patch(self, client_no_refresh: SnipeItAPIClient) -> None:
        """Successful PATCH returns parsed asset from payload key."""
        patch_response = {
            "status": "success",
            "messages": "Asset updated successfully.",
            "payload": _asset_json(42, "Updated Name"),
        }
        resp = _ok_response(patch_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            result = await client_no_refresh.update_asset(42, {"name": "Updated Name"})

        assert isinstance(result, SnipeItAsset)
        assert result.id == 42
        assert result.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_validation_error_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """PATCH returning status=error raises SnipeItAPIError."""
        error_response = {
            "status": "error",
            "messages": {"model_id": ["The selected model id is invalid."]},
        }
        resp = _ok_response(error_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="failed"):
                await client_no_refresh.update_asset(42, {"model_id": 999})

    @pytest.mark.asyncio
    async def test_missing_payload_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """PATCH returning success but no payload raises SnipeItAPIError."""
        bad_response = {"status": "success", "messages": "OK"}
        resp = _ok_response(bad_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="payload is missing"):
                await client_no_refresh.update_asset(42, {"name": "Test"})


class TestSnipeItAPIClientErrorHandling:
    """Tests for error handling in the API client."""

    @pytest.mark.asyncio
    async def test_401_raises_api_error(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """401 response raises SnipeItAPIError (API key invalid or revoked)."""
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


class TestSnipeItAPIClientListMaintenances:
    """Tests for list_maintenances method."""

    @pytest.mark.asyncio
    async def test_successful_list_fetch(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Successful GET maintenances returns parsed list."""
        resp = _ok_response(
            _maintenance_list_json(
                [
                    _maintenance_get_json(1, 10, "Inspect"),
                    _maintenance_get_json(2, 20, "Repair"),
                ],
                total=2,
            )
        )
        with patch.object(client_no_refresh._client, "get", return_value=resp):
            result = await client_no_refresh.list_maintenances()

        assert isinstance(result, SnipeItMaintenanceListResponse)
        assert result.total == 2
        assert len(result.rows) == 2
        assert result.rows[0].title == "Inspect"

    @pytest.mark.asyncio
    async def test_pagination_params_passed(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Pagination parameters are forwarded to the API call."""
        resp = _ok_response(_maintenance_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_maintenances(page=3, per_page=50)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        assert params["offset"] == 100  # (page-1) * per_page = 2*50
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_asset_id_filter(self, client_no_refresh: SnipeItAPIClient) -> None:
        """Asset ID filter is passed as query parameter."""
        resp = _ok_response(_maintenance_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_maintenances(asset_id=42)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        assert params["asset_id"] == 42

    @pytest.mark.asyncio
    async def test_path_has_no_leading_slash(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """list_maintenances uses relative path without leading /."""
        resp = _ok_response(_maintenance_list_json())
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.list_maintenances()

        path = mock_get.call_args.args[0]
        assert not path.startswith("/"), f"Path should not start with /: {path}"
        assert path == "maintenances"


class TestSnipeItAPIClientGetMaintenance:
    """Tests for get_maintenance method."""

    @pytest.mark.asyncio
    async def test_successful_get(self, client_no_refresh: SnipeItAPIClient) -> None:
        """GET maintenances/{id} returns parsed maintenance."""
        resp = _ok_response(_maintenance_get_json(101, 42, "Annual Inspection"))
        with patch.object(client_no_refresh._client, "get", return_value=resp):
            result = await client_no_refresh.get_maintenance(101)

        assert isinstance(result, SnipeItMaintenance)
        assert result.id == 101
        assert result.title == "Annual Inspection"

    @pytest.mark.asyncio
    async def test_get_maintenance_path(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """get_maintenance uses correct relative path."""
        resp = _ok_response(_maintenance_get_json(101))
        with patch.object(
            client_no_refresh._client, "get", return_value=resp
        ) as mock_get:
            await client_no_refresh.get_maintenance(101)

        path = mock_get.call_args.args[0]
        assert path == "maintenances/101"


class TestSnipeItAPIClientCreateMaintenance:
    """Tests for create_maintenance method."""

    @pytest.mark.asyncio
    async def test_successful_create(self, client_no_refresh: SnipeItAPIClient) -> None:
        """Successful POST returns parsed maintenance from payload key."""
        post_response = {
            "status": "success",
            "messages": "Asset Maintenance created successfully.",
            "payload": _maintenance_json(201, 42, "New Inspection"),
        }
        resp = _ok_response(post_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            result = await client_no_refresh.create_maintenance(
                asset_id=42,
                payload={
                    "title": "New Inspection",
                    "asset_maintenance_type": "Maintenance",
                },
            )

        assert isinstance(result, SnipeItMaintenanceWriteResponse)
        assert result.id == 201
        assert result.title == "New Inspection"

    @pytest.mark.asyncio
    async def test_validation_error_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """POST returning status=error raises SnipeItAPIError."""
        error_response = {
            "status": "error",
            "messages": {"asset_id": ["The asset id field is required."]},
        }
        resp = _ok_response(error_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="failed"):
                await client_no_refresh.create_maintenance(
                    asset_id=42, payload={"title": "Test"}
                )

    @pytest.mark.asyncio
    async def test_missing_payload_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """POST returning success but no payload raises SnipeItAPIError."""
        bad_response = {"status": "success", "messages": "OK"}
        resp = _ok_response(bad_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="payload is missing"):
                await client_no_refresh.create_maintenance(
                    asset_id=42, payload={"title": "Test"}
                )

    @pytest.mark.asyncio
    async def test_create_maintenance_path(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """create_maintenance POSTs to the correct relative path."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": _maintenance_json(201, 42, "Test"),
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.create_maintenance(
                asset_id=42, payload={"title": "Test"}
            )

        path = mock_post.call_args.args[0]
        assert path == "maintenances"

    @pytest.mark.asyncio
    async def test_create_maintenance_includes_asset_id_in_payload(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """create_maintenance injects asset_id into the JSON payload."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": _maintenance_json(201, 42, "Test"),
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.create_maintenance(
                asset_id=42, payload={"title": "Test"}
            )

        call_kwargs = mock_post.call_args.kwargs
        json_body = call_kwargs.get("json", {})
        assert json_body["asset_id"] == 42
        assert json_body["title"] == "Test"


class TestSnipeItAPIClientUpdateMaintenance:
    """Tests for update_maintenance method."""

    @pytest.mark.asyncio
    async def test_successful_patch(self, client_no_refresh: SnipeItAPIClient) -> None:
        """Successful PATCH returns parsed maintenance from payload key."""
        patch_response = {
            "status": "success",
            "messages": "Asset Maintenance updated successfully.",
            "payload": _maintenance_json(101, 42, "Updated Inspection"),
        }
        resp = _ok_response(patch_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            result = await client_no_refresh.update_maintenance(
                101, {"title": "Updated Inspection"}
            )

        assert isinstance(result, SnipeItMaintenanceWriteResponse)
        assert result.id == 101
        assert result.title == "Updated Inspection"

    @pytest.mark.asyncio
    async def test_validation_error_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """PATCH returning status=error raises SnipeItAPIError."""
        error_response = {
            "status": "error",
            "messages": {"title": ["The title field is required."]},
        }
        resp = _ok_response(error_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="failed"):
                await client_no_refresh.update_maintenance(101, {"title": ""})

    @pytest.mark.asyncio
    async def test_missing_payload_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """PATCH returning success but no payload raises SnipeItAPIError."""
        bad_response = {"status": "success", "messages": "OK"}
        resp = _ok_response(bad_response)
        with patch.object(client_no_refresh._client, "patch", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="payload is missing"):
                await client_no_refresh.update_maintenance(101, {"title": "Test"})

    @pytest.mark.asyncio
    async def test_update_maintenance_path(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """update_maintenance uses correct relative path."""
        patch_response = {
            "status": "success",
            "messages": "OK",
            "payload": _maintenance_json(101, 42, "Test"),
        }
        resp = _ok_response(patch_response)
        with patch.object(
            client_no_refresh._client, "patch", return_value=resp
        ) as mock_patch:
            await client_no_refresh.update_maintenance(101, {"title": "Test"})

        path = mock_patch.call_args.args[0]
        assert path == "maintenances/101"


class TestSnipeItAPIClientCheckoutAsset:
    """Tests for checkout_asset method."""

    @pytest.mark.asyncio
    async def test_successful_checkout(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Successful POST checkout returns parsed response dict."""
        post_response = {
            "status": "success",
            "messages": "Asset checked out successfully.",
            "payload": {"id": 42, "name": "Climbing Rope", "assigned_to": {"id": 5}},
        }
        resp = _ok_response(post_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            result = await client_no_refresh.checkout_asset(
                asset_id=42,
                payload={
                    "assigned_user": 5,
                    "checkout_to_type": "user",
                    "checkout_at": "2024-06-01",
                },
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_validation_error_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """POST checkout returning status=error raises SnipeItAPIError."""
        error_response = {
            "status": "error",
            "messages": {"assigned_user": ["The assigned user field is required."]},
        }
        resp = _ok_response(error_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="failed"):
                await client_no_refresh.checkout_asset(
                    asset_id=42, payload={"checkout_to_type": "user"}
                )

    @pytest.mark.asyncio
    async def test_checkout_asset_path(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """checkout_asset POSTs to the correct relative path."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": {"id": 42, "name": "Test"},
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.checkout_asset(
                asset_id=42,
                payload={"assigned_user": 5, "checkout_to_type": "user"},
            )

        path = mock_post.call_args.args[0]
        assert path == "hardware/42/checkout"

    @pytest.mark.asyncio
    async def test_checkout_asset_forwards_payload(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """checkout_asset forwards the payload as JSON body."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": {"id": 42, "name": "Test"},
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.checkout_asset(
                asset_id=42,
                payload={
                    "assigned_user": 5,
                    "checkout_to_type": "user",
                    "note": "Test checkout",
                },
            )

        call_kwargs = mock_post.call_args.kwargs
        json_body = call_kwargs.get("json", {})
        assert json_body["assigned_user"] == 5
        assert json_body["checkout_to_type"] == "user"
        assert json_body["note"] == "Test checkout"


class TestSnipeItAPIClientCheckinAsset:
    """Tests for checkin_asset method."""

    @pytest.mark.asyncio
    async def test_successful_checkin(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """Successful POST checkin returns parsed response dict."""
        post_response = {
            "status": "success",
            "messages": "Asset checked in successfully.",
            "payload": {"id": 42, "name": "Climbing Rope"},
        }
        resp = _ok_response(post_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            result = await client_no_refresh.checkin_asset(
                asset_id=42,
                payload={"note": "Returned after trip"},
            )

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_validation_error_raises(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """POST checkin returning status=error raises SnipeItAPIError."""
        error_response = {
            "status": "error",
            "messages": "That asset is not checked out.",
        }
        resp = _ok_response(error_response)
        with patch.object(client_no_refresh._client, "post", return_value=resp):
            with pytest.raises(SnipeItAPIError, match="failed"):
                await client_no_refresh.checkin_asset(asset_id=42, payload={})

    @pytest.mark.asyncio
    async def test_checkin_asset_path(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """checkin_asset POSTs to the correct relative path."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": {"id": 42, "name": "Test"},
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.checkin_asset(asset_id=42, payload={})

        path = mock_post.call_args.args[0]
        assert path == "hardware/42/checkin"

    @pytest.mark.asyncio
    async def test_checkin_asset_forwards_payload(
        self, client_no_refresh: SnipeItAPIClient
    ) -> None:
        """checkin_asset forwards the payload as JSON body."""
        post_response = {
            "status": "success",
            "messages": "OK",
            "payload": {"id": 42, "name": "Test"},
        }
        resp = _ok_response(post_response)
        with patch.object(
            client_no_refresh._client, "post", return_value=resp
        ) as mock_post:
            await client_no_refresh.checkin_asset(
                asset_id=42,
                payload={"note": "Usage 2024-06-01 to 2024-06-05"},
            )

        call_kwargs = mock_post.call_args.kwargs
        json_body = call_kwargs.get("json", {})
        assert json_body["note"] == "Usage 2024-06-01 to 2024-06-05"
