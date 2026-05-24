"""
Snipe-IT API v1 async client.

Provides typed methods for the Snipe-IT REST API endpoints needed for
gear item sync: asset listing and single-asset retrieval. Integrates
rate limiting.

The base URL is dynamic (self-hosted instances) and provided at
construction time from the user's ``snipeit_settings`` configuration.

Authentication uses a personal access token (API key) set as a Bearer
token in the ``Authorization`` header.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from snipeit_models import (
    SnipeItAsset,
    SnipeItAssetListResponse,
    SnipeItMaintenance,
    SnipeItMaintenanceListResponse,
)
from snipeit_rate_limiter import SnipeItRateLimiter, SnipeItRateLimitError

logger = structlog.get_logger()


class SnipeItAPIError(Exception):
    """Raised for non-retryable Snipe-IT API errors.

    Attributes:
        status_code: HTTP status code from the response.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class SnipeItAPIClient:
    """Async client for Snipe-IT API v1.

    Uses an injected ``httpx.AsyncClient`` with Bearer-token authentication
    and pre-emptive rate limiting.

    Args:
        client: Pre-configured ``httpx.AsyncClient`` (injected for testability).
        rate_limiter: Optional ``SnipeItRateLimiter`` instance (defaults to 120 req/min).
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limiter: SnipeItRateLimiter | None = None,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter or SnipeItRateLimiter()

    @classmethod
    def create(
        cls,
        base_url: str,
        api_key: str,
        requests_per_minute: int = 120,
    ) -> SnipeItAPIClient:
        """Factory: create a client with a new ``httpx.AsyncClient``.

        Convenience constructor for production use. For testing, inject
        the client directly via the constructor.

        Args:
            base_url: Snipe-IT instance base URL
                (e.g. ``https://snipeit.example.com``).
            api_key: Snipe-IT personal access token (API key).
            requests_per_minute: Rate limit for pre-emptive throttling.
        """
        client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/v1/",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        return cls(
            client=client,
            rate_limiter=SnipeItRateLimiter(requests_per_minute=requests_per_minute),
        )

    # -- Public API methods --

    async def list_assets(
        self,
        *,
        assigned_to_user_id: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> SnipeItAssetListResponse:
        """List hardware assets.

        Args:
            assigned_to_user_id: Optional Snipe-IT user ID to filter assets
                assigned to a specific user.
            page: Page number (1-based).
            per_page: Number of assets per page.

        Returns:
            Paginated asset list response.
        """
        safe_per_page = max(1, per_page)
        params: dict[str, Any] = {
            "offset": max(0, page - 1) * safe_per_page,
            "limit": safe_per_page,
        }
        if assigned_to_user_id is not None:
            params["assigned_to"] = assigned_to_user_id

        data = await self._get("hardware", params=params)
        return SnipeItAssetListResponse.model_validate(data)

    async def get_asset(self, asset_id: int) -> SnipeItAsset:
        """Fetch a single hardware asset by ID.

        Args:
            asset_id: Snipe-IT asset numeric ID.

        Returns:
            SnipeItAsset with full detail.
        """
        data = await self._get(f"hardware/{asset_id}")
        return SnipeItAsset.model_validate(data)

    async def list_maintenances(
        self,
        *,
        asset_id: int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> SnipeItMaintenanceListResponse:
        """List asset maintenance records.

        Args:
            asset_id: Optional Snipe-IT asset ID to filter maintenances
                for a specific asset.
            page: Page number (1-based).
            per_page: Number of records per page.

        Returns:
            Paginated maintenance list response.
        """
        safe_per_page = max(1, per_page)
        params: dict[str, Any] = {
            "offset": max(0, page - 1) * safe_per_page,
            "limit": safe_per_page,
        }
        if asset_id is not None:
            params["asset_id"] = asset_id

        data = await self._get("maintenances", params=params)
        return SnipeItMaintenanceListResponse.model_validate(data)

    async def get_maintenance(self, maintenance_id: int) -> SnipeItMaintenance:
        """Fetch a single maintenance record by ID.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.

        Returns:
            SnipeItMaintenance with full detail.
        """
        data = await self._get(f"maintenances/{maintenance_id}")
        return SnipeItMaintenance.model_validate(data)

    async def update_asset(
        self, asset_id: int, payload: dict[str, Any]
    ) -> SnipeItAsset:
        """Update an existing hardware asset.

        Snipe-IT PATCH responses are wrapped as
        ``{"status": "success", "messages": "...", "payload": {...}}``.
        The API returns HTTP 200 even on validation errors, so we must
        inspect the ``status`` field before extracting the asset from
        ``payload``.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            payload: Fields to update (e.g. name, serial, notes).

        Returns:
            SnipeItAsset parsed from the ``payload`` key of a successful
            response.

        Raises:
            SnipeItAPIError: If the response ``status`` is not ``"success"``
                or the ``payload`` key is missing/unparseable.
        """
        data = await self._patch(f"hardware/{asset_id}", json_data=payload)

        # Snipe-IT returns HTTP 200 for validation errors; check status.
        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT PATCH /hardware/{asset_id} failed: {messages}",
                status_code=200,
            )

        asset_payload = data.get("payload")
        if not asset_payload or not isinstance(asset_payload, dict):
            raise SnipeItAPIError(
                f"Snipe-IT PATCH /hardware/{asset_id} returned success "
                f"but payload is missing or invalid",
                status_code=200,
            )

        return SnipeItAsset.model_validate(asset_payload)

    async def checkout_asset(
        self, asset_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Check out an asset to a user in Snipe-IT.

        Sends ``POST /hardware/{asset_id}/checkout`` with the given payload.
        The checkout response is returned as a raw dict because it differs
        from the standard asset response structure.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            payload: Checkout fields (assigned_user, checkout_to_type,
                checkout_at, expected_checkin, note).

        Returns:
            Raw response dict from Snipe-IT.

        Raises:
            SnipeItAPIError: If the response ``status`` is not ``"success"``.
        """
        data: dict[str, Any] = await self._post(
            f"hardware/{asset_id}/checkout", json_data=payload
        )

        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT POST /hardware/{asset_id}/checkout failed: {messages}",
                status_code=200,
            )

        return data

    async def create_maintenance(
        self, asset_id: int, payload: dict[str, Any]
    ) -> SnipeItMaintenance:
        """Create a new asset maintenance record.

        Snipe-IT POST responses are wrapped as
        ``{"status": "success", "messages": "...", "payload": {...}}``.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            payload: Maintenance fields (title, asset_maintenance_type, etc.).

        Returns:
            SnipeItMaintenance parsed from the ``payload`` key.

        Raises:
            SnipeItAPIError: If the response ``status`` is not ``"success"``
                or the ``payload`` key is missing/unparseable.
        """
        full_payload = {**payload, "asset_id": asset_id}
        data = await self._post("maintenances", json_data=full_payload)

        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT POST /maintenances failed: {messages}",
                status_code=200,
            )

        maintenance_payload = data.get("payload")
        if not maintenance_payload or not isinstance(maintenance_payload, dict):
            raise SnipeItAPIError(
                "Snipe-IT POST /maintenances returned success "
                "but payload is missing or invalid",
                status_code=200,
            )

        return SnipeItMaintenance.model_validate(maintenance_payload)

    async def update_maintenance(
        self, maintenance_id: int, payload: dict[str, Any]
    ) -> SnipeItMaintenance:
        """Update an existing asset maintenance record.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.
            payload: Fields to update (e.g. title, notes).

        Returns:
            SnipeItMaintenance parsed from the ``payload`` key.

        Raises:
            SnipeItAPIError: If the response ``status`` is not ``"success"``
                or the ``payload`` key is missing/unparseable.
        """
        data = await self._patch(f"maintenances/{maintenance_id}", json_data=payload)

        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT PATCH /maintenances/{maintenance_id} failed: {messages}",
                status_code=200,
            )

        maintenance_payload = data.get("payload")
        if not maintenance_payload or not isinstance(maintenance_payload, dict):
            raise SnipeItAPIError(
                f"Snipe-IT PATCH /maintenances/{maintenance_id} returned success "
                f"but payload is missing or invalid",
                status_code=200,
            )

        return SnipeItMaintenance.model_validate(maintenance_payload)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Internal helpers --

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a GET request with rate limiting.

        Args:
            path: API path relative to base URL (e.g. ``hardware``).
                Must NOT start with ``/`` (httpx would discard the
                base URL path component).
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.
        """
        # Pre-emptive rate limit check and record
        self._rate_limiter.acquire()

        response = await self._client.get(path, params=params)

        # Handle 401 — API key invalid or revoked
        if response.status_code == 401:
            raise SnipeItAPIError(
                "Snipe-IT authentication failed (invalid API key)",
                status_code=401,
            )

        # Handle 429 — rate limited by server
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            retry_msg = f"{retry_after}s" if retry_after is not None else "unknown time"
            raise SnipeItRateLimitError(
                f"Snipe-IT API rate limited (429). Retry after {retry_msg}.",
                retry_after=retry_after,
            )

        # Handle other non-successful responses
        if response.status_code >= 300:
            raise SnipeItAPIError(
                f"Snipe-IT API error: {response.status_code}",
                status_code=response.status_code,
            )

        return response.json()

    async def _patch(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a PATCH request with rate limiting.

        Args:
            path: API path relative to base URL (e.g. ``hardware/1``).
            json_data: JSON payload for the update.

        Returns:
            Parsed JSON response body.
        """
        # Pre-emptive rate limit check and record
        self._rate_limiter.acquire()

        response = await self._client.patch(path, json=json_data)

        # Handle 401 — API key invalid or revoked
        if response.status_code == 401:
            raise SnipeItAPIError(
                "Snipe-IT authentication failed (invalid API key)",
                status_code=401,
            )

        # Handle 429 — rate limited by server
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            retry_msg = f"{retry_after}s" if retry_after is not None else "unknown time"
            raise SnipeItRateLimitError(
                f"Snipe-IT API rate limited (429). Retry after {retry_msg}.",
                retry_after=retry_after,
            )

        # Handle other non-successful responses
        if response.status_code >= 300:
            raise SnipeItAPIError(
                f"Snipe-IT API error: {response.status_code}",
                status_code=response.status_code,
            )

        return response.json()

    async def _post(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a POST request with rate limiting.

        Args:
            path: API path relative to base URL (e.g. ``maintenances``).
            json_data: JSON payload for the creation.

        Returns:
            Parsed JSON response body.
        """
        # Pre-emptive rate limit check and record
        self._rate_limiter.acquire()

        response = await self._client.post(path, json=json_data)

        # Handle 401 — API key invalid or revoked
        if response.status_code == 401:
            raise SnipeItAPIError(
                "Snipe-IT authentication failed (invalid API key)",
                status_code=401,
            )

        # Handle 429 — rate limited by server
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            retry_msg = f"{retry_after}s" if retry_after is not None else "unknown time"
            raise SnipeItRateLimitError(
                f"Snipe-IT API rate limited (429). Retry after {retry_msg}.",
                retry_after=retry_after,
            )

        # Handle other non-successful responses
        if response.status_code >= 300:
            raise SnipeItAPIError(
                f"Snipe-IT API error: {response.status_code}",
                status_code=response.status_code,
            )

        return response.json()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value defensively.

    Snipe-IT sends ``Retry-After`` as delta-seconds (integer).
    This function handles non-numeric or missing values gracefully.

    Args:
        value: Raw header value (may be None, integer string, or date).

    Returns:
        Numeric seconds to wait, or ``None`` if unparseable.
    """
    if not value:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning("Could not parse Retry-After header", raw_value=value)
        return None
