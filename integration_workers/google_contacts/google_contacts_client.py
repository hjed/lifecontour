"""
Google Contacts API Client for Worker.

Handles communication with Google People API for contacts synchronization.
"""

import logging
from typing import Any, cast

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.credentials import Credentials
from google.oauth2.credentials import Credentials as OAuth2Credentials

from google_auth_service import GoogleAuthService, GoogleAuthTokensNotFoundError

logger = structlog.get_logger()


class GoogleContactsAPIClient:
    """Client for Google People API operations."""

    def __init__(
        self,
        auth_service: GoogleAuthService,
        google_account_email: str,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        """
        Initialize the Google Contacts API client.

        Args:
            auth_service: Google authentication service
            google_account_email: Google account email to use for API calls
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
        """
        self.auth_service = auth_service
        self.google_account_email = google_account_email
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self._service = None

    async def _get_service(self):
        """Get or create Google People API service with authentication."""
        if self._service is None:
            try:
                # Get access token
                access_token = await self.auth_service.get_access_token(
                    self.google_account_email
                )

                # Create credentials
                credentials = OAuth2Credentials(
                    token=access_token,
                    client_id=self.google_client_id,
                    client_secret=self.google_client_secret,
                )

                # Build the service
                self._service = build(
                    "people", "v1", credentials=credentials, cache_discovery=False
                )

                logger.info(
                    "Created Google People API service",
                    google_account_email=self.google_account_email,
                )

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
        List contacts from Google People API.

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
                "Fetching Google contacts",
                google_account_email=self.google_account_email,
                page_size=page_size,
                has_page_token=bool(page_token),
                has_sync_token=bool(sync_token),
            )

            # Make the API call
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

    async def get_person(self, resource_name: str) -> dict[str, Any]:
        """
        Get a specific person from Google People API.

        Args:
            resource_name: Resource name of the person (e.g., "people/c123456789")

        Returns:
            Google People API person data

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_service()

            logger.info(
                "Fetching Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            # Make the API call
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
