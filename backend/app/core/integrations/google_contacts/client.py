"""
Google Contacts API client with automatic token refresh.

Provides a clean interface to the Google People API with automatic
OAuth token refresh on 401 responses.
"""

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog

from app.core.integrations.google_contacts.service import (
    GoogleAuthService,
    TokenRefreshFailedError,
)

logger = structlog.get_logger()


class GoogleAuth(httpx.Auth):
    """
    Custom httpx authentication handler for Google API with automatic token refresh.

    Handles 401 responses by automatically refreshing the access token
    and retrying the request.
    """

    def __init__(
        self, auth_service: GoogleAuthService, google_account_email: str
    ) -> None:
        """
        Initialize Google authentication handler.

        Args:
            auth_service: Service for managing Google OAuth tokens
            google_account_email: Google account email for token lookup
        """
        self.auth_service = auth_service
        self.google_account_email = google_account_email
        self._access_token: str | None = None

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """
        Handle authentication flow with automatic token refresh.

        Args:
            request: HTTP request to authenticate

        Yields:
            Authenticated HTTP request
        """
        # Get initial token if not cached
        if not self._access_token:
            try:
                self._access_token = await self.auth_service.get_access_token(
                    self.google_account_email
                )
            except ValueError as e:
                logger.error(
                    "No Google auth tokens found",
                    google_account_email=self.google_account_email,
                    error=str(e),
                )
                # Let the request proceed without auth - it will fail with 401
                # and the caller can handle the authentication error
                yield request
                return

        # Add authorization header
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        response = yield request

        # Check if token expired and refresh if needed
        if response.status_code == 401:
            logger.info(
                "Google API returned 401, attempting token refresh",
                google_account_email=self.google_account_email,
            )

            try:
                # Refresh the token
                self._access_token = await self.auth_service.refresh_access_token(
                    self.google_account_email
                )

                # Retry the request with new token
                request.headers["Authorization"] = f"Bearer {self._access_token}"
                yield request

            except TokenRefreshFailedError as e:
                logger.error(
                    "Google token refresh failed permanently",
                    google_account_email=self.google_account_email,
                    error=str(e),
                )
                # Don't yield another request - let the 401 response be returned
                # The caller should handle this as an authentication failure


class GoogleContactsAPIClient:
    """
    Client for Google People API with automatic authentication.

    Provides methods for accessing Google Contacts data with automatic
    OAuth token management and refresh.
    """

    def __init__(
        self, auth_service: GoogleAuthService, google_account_email: str
    ) -> None:
        """
        Initialize Google Contacts API client.

        Args:
            auth_service: Service for managing Google OAuth tokens
            google_account_email: Google account email for API access
        """
        self.google_account_email = google_account_email
        self.auth = GoogleAuth(auth_service, google_account_email)
        self.client = httpx.AsyncClient(
            auth=self.auth,
            base_url="https://people.googleapis.com",
            timeout=30.0,
        )

    async def __aenter__(self) -> "GoogleContactsAPIClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.client.aclose()

    async def list_connections(
        self,
        page_size: int = 100,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        """
        List contacts from Google People API.

        Args:
            page_size: Number of contacts to return per page (max 2000)
            page_token: Token for pagination
            sync_token: Token for incremental sync

        Returns:
            Google People API response with contacts data

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        params: dict[str, str | int] = {
            "resourceName": "people/me",
            "pageSize": min(page_size, 2000),  # Google's max limit
            "personFields": "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata",
        }

        if page_token:
            params["pageToken"] = page_token
        if sync_token:
            params["syncToken"] = sync_token

        logger.info(
            "Fetching Google contacts",
            google_account_email=self.google_account_email,
            page_size=page_size,
            has_page_token=bool(page_token),
            has_sync_token=bool(sync_token),
        )

        response = await self.client.get("/v1/people/me/connections", params=params)
        response.raise_for_status()

        data: dict[str, Any] = response.json()

        logger.info(
            "Successfully fetched Google contacts",
            google_account_email=self.google_account_email,
            total_items=len(data.get("connections", [])),
            next_page_token=data.get("nextPageToken"),
            next_sync_token=data.get("nextSyncToken"),
        )

        return data

    async def get_contact(self, resource_name: str) -> dict[str, Any]:
        """
        Get a specific contact by resource name.

        Args:
            resource_name: Google contact resource name (e.g., "people/123")

        Returns:
            Google People API contact data

        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        params = {
            "personFields": "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata"
        }

        logger.info(
            "Fetching Google contact",
            google_account_email=self.google_account_email,
            resource_name=resource_name,
        )

        response = await self.client.get(f"/v1/{resource_name}", params=params)
        response.raise_for_status()

        data: dict[str, Any] = response.json()

        logger.info(
            "Successfully fetched Google contact",
            google_account_email=self.google_account_email,
            resource_name=resource_name,
        )

        return data

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
