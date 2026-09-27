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

import asyncio
from typing import Any

import httpx
import structlog

from snipeit_models import (
    SnipeItActivityListResponse,
    SnipeItAsset,
    SnipeItAssetListResponse,
    SnipeItAssetStatusFilter,
    SnipeItMaintenance,
    SnipeItMaintenanceListResponse,
    SnipeItMaintenanceWriteResponse,
)
from snipeit_rate_limiter import (
    SnipeItRateLimiter,
    SnipeItRateLimitError,
    rate_limiter_for,
)

logger = structlog.get_logger()

# A 429 from Snipe-IT's throttle is retried this many times before it is raised.
# Each wait is Snipe-IT's Retry-After, or an exponential backoff without one,
# and never longer than the cap: the stream consumer handles one event at a
# time, so a long sleep here holds up every other event.
_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_BACKOFF_BASE = 2.0
_RATE_LIMIT_MAX_WAIT = 30.0


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
        wait_on_limit: When the limiter's budget is spent, wait for a slot
            rather than raise ``SnipeItRateLimitError``. Callers that can only
            retry an event wholesale wait; batch jobs that defer themselves on
            the error leave it off.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limiter: SnipeItRateLimiter | None = None,
        *,
        wait_on_limit: bool = False,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter or SnipeItRateLimiter()
        self._wait_on_limit = wait_on_limit

    @classmethod
    def create(
        cls,
        base_url: str,
        api_key: str,
        requests_per_minute: int = 120,
        *,
        wait_on_limit: bool = False,
    ) -> SnipeItAPIClient:
        """Factory: create a client with a new ``httpx.AsyncClient``.

        Convenience constructor for production use. For testing, inject
        the client directly via the constructor. The client shares the
        worker's limiter for this API key on this Snipe-IT instance (see
        :func:`rate_limiter_for`), so every client using the key spends one
        budget.

        Args:
            base_url: Snipe-IT instance base URL
                (e.g. ``https://snipeit.example.com``).
            api_key: Snipe-IT personal access token (API key).
            requests_per_minute: Rate limit for pre-emptive throttling.
            wait_on_limit: See the class docstring.
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
            rate_limiter=rate_limiter_for(base_url, api_key, requests_per_minute),
            wait_on_limit=wait_on_limit,
        )

    # -- Public API methods --

    async def list_assets(
        self,
        *,
        assigned_to_user_id: str | None = None,
        status: SnipeItAssetStatusFilter | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> SnipeItAssetListResponse:
        """List hardware assets.

        Args:
            assigned_to_user_id: Optional Snipe-IT user ID to filter assets
                assigned to a specific user.
            status: Optional status filter. Without one Snipe-IT's default
                listing leaves out archived assets.
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
        if status is not None:
            params["status"] = status.value

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

    async def list_asset_activity(
        self,
        asset_id: int,
        *,
        action_type: str,
        page: int = 1,
        per_page: int = 50,
    ) -> SnipeItActivityListResponse:
        """List an asset's activity log entries of one action type, newest first.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            action_type: Snipe-IT action type, e.g. ``checkout`` or
                ``checkin from``.
            page: Page number (1-based).
            per_page: Number of records per page.

        Returns:
            Paginated activity list response.
        """
        safe_per_page = max(1, per_page)
        params: dict[str, Any] = {
            "item_type": "asset",
            "item_id": asset_id,
            "action_type": action_type,
            "sort": "id",
            "order": "desc",
            "offset": max(0, page - 1) * safe_per_page,
            "limit": safe_per_page,
        }
        data = await self._get("reports/activity", params=params)
        return SnipeItActivityListResponse.model_validate(data)

    async def get_maintenance(self, maintenance_id: int) -> SnipeItMaintenance:
        """Fetch a single maintenance record by ID.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.

        Returns:
            SnipeItMaintenance with full detail.
        """
        data = await self._get(f"maintenances/{maintenance_id}")
        return SnipeItMaintenance.model_validate(data)

    async def maintenance_exists(self, maintenance_id: int) -> bool:
        """Whether Snipe-IT still has this maintenance record.

        Snipe-IT answers a missing record with a 404, or with HTTP 200 and an
        error body saying it was not found. Both mean the record is gone. Any
        other error says nothing about the record, so it raises.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.

        Returns:
            ``False`` only when Snipe-IT says it has no such record.

        Raises:
            SnipeItAPIError: If Snipe-IT could not answer the question.
            SnipeItRateLimitError: If Snipe-IT rate limited the request.
        """
        try:
            data = await self._get(f"maintenances/{maintenance_id}")
        except SnipeItAPIError as exc:
            if exc.status_code == 404:
                return False
            raise

        if data.get("status") == "error":
            messages = str(data.get("messages", ""))
            if messages.lower().endswith("not found"):
                return False
            raise SnipeItAPIError(
                f"Snipe-IT GET /maintenances/{maintenance_id} failed: {messages}",
                status_code=200,
            )
        return True

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

        ``checkout_at`` may be a date or a ``YYYY-MM-DD HH:MM:SS`` datetime in
        Snipe-IT's zone; Snipe-IT stores it verbatim as the asset's
        ``last_checkout`` and dates the checkout log with it, time included.

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

    async def checkin_asset(
        self, asset_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Check in (return) an asset in Snipe-IT.

        Sends ``POST /hardware/{asset_id}/checkin`` with the given payload.
        The checkin response is returned as a raw dict because it differs
        from the standard asset response structure.

        Pass ``checkin_at`` (``YYYY-MM-DD``) to backdate the return's log entry.
        The field is missing from Snipe-IT's API reference but is read by
        ``Api\\AssetsController::checkin``: Snipe-IT appends its current time and
        sets the log's ``action_date`` when the date is not the server's today,
        so it must be a date, never a datetime. Either way the asset's
        ``last_checkin`` is set to the server's current time.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            payload: Checkin fields (e.g. note, checkin_at, location_id,
                status_id).

        Returns:
            Raw response dict from Snipe-IT.

        Raises:
            SnipeItAPIError: If the response ``status`` is not ``"success"``.
        """
        data: dict[str, Any] = await self._post(
            f"hardware/{asset_id}/checkin", json_data=payload
        )

        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT POST /hardware/{asset_id}/checkin failed: {messages}",
                status_code=200,
            )

        return data

    async def create_maintenance(
        self, asset_id: int, payload: dict[str, Any]
    ) -> SnipeItMaintenanceWriteResponse:
        """Create a new asset maintenance record.

        Snipe-IT POST responses are wrapped as
        ``{"status": "success", "messages": "...", "payload": {...}}``.

        Args:
            asset_id: Snipe-IT asset numeric ID.
            payload: Maintenance fields (title, asset_maintenance_type, etc.).

        Returns:
            SnipeItMaintenanceWriteResponse parsed from the ``payload`` key.

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

        return SnipeItMaintenanceWriteResponse.model_validate(maintenance_payload)

    async def update_maintenance(
        self, maintenance_id: int, payload: dict[str, Any]
    ) -> SnipeItMaintenanceWriteResponse:
        """Update an existing asset maintenance record.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.
            payload: Fields to update (e.g. title, notes).

        Returns:
            SnipeItMaintenanceWriteResponse parsed from the ``payload`` key.

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

        return SnipeItMaintenanceWriteResponse.model_validate(maintenance_payload)

    async def delete_maintenance(self, maintenance_id: int) -> bool:
        """Delete an asset maintenance record.

        Called when the ``GEAR_MAINTENANCE`` journal that pushed the record is
        deleted, so the record does not outlive its journal and come back as a
        new one on the next import.

        Args:
            maintenance_id: Snipe-IT maintenance numeric ID.

        Returns:
            ``True`` when Snipe-IT deleted the record, ``False`` when it has no
            such record: already gone is the state the caller asked for.

        Raises:
            SnipeItAPIError: If the record could not be deleted, including a
                response whose ``status`` is not ``"success"``.
            SnipeItRateLimitError: If Snipe-IT rate limited the request.
        """
        try:
            data = await self._delete(f"maintenances/{maintenance_id}")
        except SnipeItAPIError as exc:
            if exc.status_code == 404:
                logger.debug(
                    "Snipe-IT maintenance already deleted",
                    maintenance_id=maintenance_id,
                )
                return False
            raise

        if data.get("status") != "success":
            messages = data.get("messages", "Unknown error")
            raise SnipeItAPIError(
                f"Snipe-IT DELETE /maintenances/{maintenance_id} failed: {messages}",
                status_code=200,
            )

        return True

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Internal helpers --

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a GET request.

        Args:
            path: API path relative to base URL (e.g. ``hardware``).
                Must NOT start with ``/`` (httpx would discard the
                base URL path component).
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.
        """
        return await self._request("GET", path, params=params)

    async def _patch(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a PATCH request (e.g. ``hardware/1``) with a JSON payload."""
        return await self._request("PATCH", path, json=json_data)

    async def _post(
        self,
        path: str,
        json_data: dict[str, Any],
    ) -> Any:
        """Execute a POST request (e.g. ``maintenances``) with a JSON payload."""
        return await self._request("POST", path, json=json_data)

    async def _delete(self, path: str) -> Any:
        """Execute a DELETE request (e.g. ``maintenances/1``)."""
        return await self._request("DELETE", path)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send one request within the rate limit and return its JSON body.

        Shared by every verb, so a verb added later cannot quietly skip the
        rate limiting or the error handling the others do.

        A 429 is sent again after a wait (see ``_RATE_LIMIT_RETRIES``). That is
        safe for a POST too: Snipe-IT's throttle rejects a request before it
        reaches the controller. Nothing else is retried here, since a POST that
        timed out or failed with a 5xx may have landed.
        """
        send = getattr(self._client, method.lower())
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            if self._wait_on_limit:
                await self._rate_limiter.wait_for_slot()
            else:
                self._rate_limiter.acquire()

            response = await send(path, **kwargs)
            try:
                _raise_for_response(response)
            except SnipeItRateLimitError as exc:
                if attempt == _RATE_LIMIT_RETRIES:
                    raise
                wait = min(
                    exc.retry_after
                    if exc.retry_after is not None
                    else _RATE_LIMIT_BACKOFF_BASE ** (attempt + 1),
                    _RATE_LIMIT_MAX_WAIT,
                )
                logger.info(
                    "Snipe-IT rate limited a request; retrying",
                    method=method,
                    path=path,
                    wait_seconds=wait,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)
                continue
            return response.json()
        raise AssertionError("unreachable")  # pragma: no cover


def _raise_for_response(response: httpx.Response) -> None:
    """Turn a non-successful Snipe-IT response into this module's errors.

    Shared by every verb, so a verb added later cannot quietly skip the 401
    and 429 handling the others do.

    Raises:
        SnipeItAPIError: On 401, or on any other status at or above 300.
        SnipeItRateLimitError: On 429, carrying the ``Retry-After`` delay.
    """
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
