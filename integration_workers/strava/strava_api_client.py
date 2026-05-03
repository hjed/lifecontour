"""
Strava API v3 async client.

Provides typed methods for the Strava REST API endpoints needed for
activity import: athlete profile, activity listing, activity detail,
and activity streams. Integrates rate limiting and automatic token
refresh on 401 responses.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from strava_auth_service import StravaAuthService
from strava_models import (
    StravaActivity,
    StravaAthlete,
    StravaStreamSet,
)
from strava_rate_limiter import StravaRateLimiter, StravaRateLimitError

logger = structlog.get_logger()

_STRAVA_BASE_URL = "https://www.strava.com/api/v3/"


class StravaAPIError(Exception):
    """Raised for non-retryable Strava API errors.

    Attributes:
        status_code: HTTP status code from the response.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class StravaAPIClient:
    """Async client for Strava API v3.

    Uses ``httpx.AsyncClient`` with Bearer-token authentication, automatic
    rate limiting, and transparent token refresh on 401 responses.

    Args:
        access_token: Current Strava OAuth access token.
        refresh_token_value: Current refresh token for re-authentication.
        auth_service: ``StravaAuthService`` used for token refresh.
    """

    def __init__(
        self,
        access_token: str,
        refresh_token_value: str,
        auth_service: StravaAuthService,
    ) -> None:
        self._access_token = access_token
        self._refresh_token_value = refresh_token_value
        self._auth_service = auth_service
        self._rate_limiter = StravaRateLimiter()
        self._client = httpx.AsyncClient(
            base_url=_STRAVA_BASE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    # -- Public API methods --

    async def get_athlete(self) -> StravaAthlete:
        """Fetch the authenticated athlete's profile.

        Returns:
            StravaAthlete with profile data.

        Raises:
            StravaAPIError: On non-retryable errors.
            StravaRateLimitError: When rate limits are exceeded.
        """
        data = await self._get("athlete")
        return StravaAthlete.model_validate(data)

    async def list_activities(
        self,
        *,
        after: int | None = None,
        before: int | None = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[StravaActivity]:
        """List the authenticated athlete's activities.

        Args:
            after: Epoch timestamp — only return activities after this time.
            before: Epoch timestamp — only return activities before this time.
            page: Page number for pagination (1-based).
            per_page: Number of activities per page (max 200).

        Returns:
            List of StravaActivity models.
        """
        params: dict[str, str | int] = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before

        data = await self._get("athlete/activities", params=params)
        return [StravaActivity.model_validate(item) for item in data]

    async def get_activity(self, activity_id: int) -> StravaActivity:
        """Fetch full detail for a single activity.

        Args:
            activity_id: Strava's numeric activity identifier.

        Returns:
            StravaActivity with full detail including ``start_latlng``.
        """
        data = await self._get(f"activities/{activity_id}")
        return StravaActivity.model_validate(data)

    async def get_activity_streams(
        self,
        activity_id: int,
        keys: list[str] | None = None,
    ) -> StravaStreamSet:
        """Fetch data streams for an activity.

        Used for GPX generation — typically requests ``latlng``, ``altitude``,
        and ``time`` streams.

        Args:
            activity_id: Strava's numeric activity identifier.
            keys: Stream types to fetch (default: latlng, altitude, time).

        Returns:
            StravaStreamSet grouping streams by type.
        """
        if keys is None:
            keys = ["latlng", "altitude", "time"]

        stream_params: dict[str, str | int] = {
            "keys": ",".join(keys),
            "key_by_type": "false",
        }
        data = await self._get(
            f"activities/{activity_id}/streams", params=stream_params
        )
        return StravaStreamSet.from_api_response(data)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # -- Internal helpers --

    async def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        _is_retry: bool = False,
    ) -> Any:
        """Execute a GET request with rate limiting and 401 refresh.

        Args:
            path: API path relative to base URL (e.g. ``athlete``).
            params: Optional query parameters.
            _is_retry: Internal flag to prevent infinite refresh loops.

        Returns:
            Parsed JSON response body.
        """
        # Pre-emptive rate limit check
        self._rate_limiter.check()

        response = await self._client.get(path, params=params)

        # Synchronise rate limiter from server-reported usage.
        # Strava's X-RateLimit-Usage already includes this request, so we
        # do NOT call record_request() when headers are present to avoid
        # double-counting.
        self._rate_limiter.update_from_headers(response.headers)

        # Handle 401 — token refresh and retry
        if response.status_code == 401 and not _is_retry:
            logger.info("Strava API returned 401 — refreshing token")
            try:
                new_tokens = await self._auth_service.refresh_token(
                    self._refresh_token_value
                )
                self._access_token = new_tokens.access_token
                self._refresh_token_value = new_tokens.refresh_token
                self._client.headers["Authorization"] = (
                    f"Bearer {new_tokens.access_token}"
                )
                return await self._get(path, params=params, _is_retry=True)
            except Exception:
                logger.error("Token refresh failed", exc_info=True)
                raise StravaAPIError(
                    "Strava authentication failed after token refresh",
                    status_code=401,
                ) from None

        # Handle 429 — rate limited by Strava
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise StravaRateLimitError(
                f"Strava API rate limited (429). Retry after {retry_after}s.",
                retry_after=float(retry_after) if retry_after else None,
            )

        # Handle other errors
        if response.status_code >= 400:
            raise StravaAPIError(
                f"Strava API error: {response.status_code}",
                status_code=response.status_code,
            )

        return response.json()
