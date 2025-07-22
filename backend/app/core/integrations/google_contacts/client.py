"""
Google Contacts API client using official Google Python client library.

Provides a clean interface to the Google People API with automatic
OAuth token refresh and proper credential management using the official
google-api-python-client library.
"""

from typing import Any, cast

import structlog
from google.oauth2.credentials import Credentials as OAuth2Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.integrations.google_contacts.service import (
    GoogleAuthService,
    GoogleAuthTokensNotFoundError,
    TokenRefreshFailedError,
)

logger = structlog.get_logger()


class GoogleCredentials(OAuth2Credentials):
    """
    Custom Google OAuth2 credentials with automatic token refresh.

    Integrates with our GoogleAuthService to provide automatic token refresh
    for the official Google API client library.
    """

    def __init__(
        self,
        auth_service: GoogleAuthService,
        google_account_email: str,
        access_token: str,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        """
        Initialize Google credentials with auto-refresh capability.

        Args:
            auth_service: Service for managing Google OAuth tokens
            google_account_email: Google account email for token lookup
            access_token: Current access token
            refresh_token: Refresh token for automatic renewal
            client_id: Google OAuth client ID
            client_secret: Google OAuth client secret
        """
        super().__init__(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.auth_service = auth_service
        self.google_account_email = google_account_email

    async def refresh(self, request: Any) -> None:
        """
        Refresh the access token using our auth service.

        This method is called automatically by the Google client library
        when the access token expires.

        Args:
            request: HTTP request object (unused in our implementation)
        """
        try:
            logger.info(
                "Refreshing Google access token",
                google_account_email=self.google_account_email,
            )

            # Use our auth service to refresh the token
            new_access_token = await self.auth_service.refresh_access_token(
                self.google_account_email
            )

            # Update the credentials
            self.token = new_access_token

            logger.info(
                "Successfully refreshed Google access token",
                google_account_email=self.google_account_email,
            )

        except TokenRefreshFailedError as e:
            logger.error(
                "Failed to refresh Google access token",
                google_account_email=self.google_account_email,
                error=str(e),
            )
            raise e


class GoogleContactsAPIClient:
    """
    Client for Google People API using official Google Python client library.

    Provides methods for accessing Google Contacts data with automatic
    OAuth token management and refresh using the official google-api-python-client.
    """

    def __init__(
        self,
        auth_service: GoogleAuthService,
        google_account_email: str,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        """
        Initialize Google Contacts API client.

        Args:
            auth_service: Service for managing Google OAuth tokens
            google_account_email: Google account email for API access
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
        """
        self.auth_service = auth_service
        self.google_account_email = google_account_email
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self._service = None

    async def _get_service(self) -> Any:
        """
        Get or create the Google People API service with proper credentials.

        Returns:
            Google People API service instance
        """
        if self._service is None:
            try:
                # Get current access token
                access_token = await self.auth_service.get_access_token(
                    self.google_account_email
                )

                # Get refresh token (if available)
                refresh_token = await self.auth_service.get_refresh_token(
                    self.google_account_email
                )

                # Create credentials
                credentials = GoogleCredentials(
                    auth_service=self.auth_service,
                    google_account_email=self.google_account_email,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    client_id=self.google_client_id,
                    client_secret=self.google_client_secret,
                )

                # Build the service
                self._service = build("people", "v1", credentials=credentials)

            except GoogleAuthTokensNotFoundError as e:
                logger.error(
                    "No Google auth tokens found",
                    google_account_email=self.google_account_email,
                    error=str(e),
                )
                raise GoogleAuthTokensNotFoundError(
                    f"Google OAuth tokens not found for {self.google_account_email}. "
                    "Please authenticate with Google first."
                ) from e

        return self._service

    async def list_connections(
        self,
        page_size: int = 100,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        """
        List contacts from Google People API using official client library.

        Args:
            page_size: Number of contacts to return per page (max 2000)
            page_token: Token for pagination
            sync_token: Token for incremental sync

        Returns:
            Google People API response with contacts data

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_service()

            # Build request parameters
            request_params = {
                "resourceName": "people/me",
                "pageSize": min(page_size, 2000),  # Google's max limit
                "personFields": "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata",
            }

            if page_token:
                request_params["pageToken"] = page_token
            if sync_token:
                request_params["syncToken"] = sync_token

            logger.info(
                "Fetching Google contacts using official client",
                google_account_email=self.google_account_email,
                page_size=page_size,
                has_page_token=bool(page_token),
                has_sync_token=bool(sync_token),
            )

            # Make the API call using official client
            result = service.people().connections().list(**request_params).execute()

            logger.info(
                "Successfully fetched Google contacts",
                google_account_email=self.google_account_email,
                total_items=len(result.get("connections", [])),
                next_page_token=result.get("nextPageToken"),
                next_sync_token=result.get("nextSyncToken"),
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            logger.error(
                "Google API error while fetching contacts",
                google_account_email=self.google_account_email,
                error=str(e),
                status_code=e.resp.status,
            )
            raise e

    async def get_contact(self, resource_name: str) -> dict[str, Any]:
        """
        Get a specific contact by resource name using official client library.

        Args:
            resource_name: Google contact resource name (e.g., "people/123")

        Returns:
            Google People API contact data

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_service()

            logger.info(
                "Fetching Google contact using official client",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            # Make the API call using official client
            result = (
                service.people()
                .get(
                    resourceName=resource_name,
                    personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata",
                )
                .execute()
            )

            logger.info(
                "Successfully fetched Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            logger.error(
                "Google API error while fetching contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                error=str(e),
                status_code=e.resp.status,
            )
            raise e

    async def close(self) -> None:
        """Close any resources (no-op for official client)."""
        # The official Google client doesn't require explicit cleanup
        pass
