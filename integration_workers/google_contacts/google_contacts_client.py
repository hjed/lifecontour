"""
Google Contacts API client for worker.

Simplified version of the core client adapted for worker environment.
Migrated from backend/app/core/integrations/google_contacts/client.py
"""

from typing import Any, cast

import structlog
from google.oauth2.credentials import Credentials as OAuth2Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
        user_id: str | int,
    ) -> None:
        """
        Initialize the Google Contacts API client.

        Args:
            auth_service: Google authentication service
            google_account_email: Google account email to use for API calls
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
            user_id: User ID in the system
        """
        self.auth_service = auth_service
        self.google_account_email = google_account_email
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.user_id = user_id
        self._service: Any | None = None

    async def _get_service(self) -> Any:
        """Get or create Google People API service with authentication."""
        if self._service is None:
            try:
                # Get access token
                access_token = await self.auth_service.get_access_token(
                    self.user_id, self.google_account_email
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

    async def create_contact(self, contact_data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new contact in Google People API.

        Args:
            contact_data: Contact data in Google People API format
                         (names, emailAddresses, phoneNumbers, etc.)

        Returns:
            Created contact data from Google People API including resourceName and etag

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_service()

            logger.info(
                "Creating Google contact",
                google_account_email=self.google_account_email,
            )

            # Make the API call
            result = service.people().createContact(body=contact_data).execute()

            logger.info(
                "Successfully created Google contact",
                google_account_email=self.google_account_email,
                resource_name=result.get("resourceName"),
                etag=result.get("etag"),
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            logger.error(
                "Google API error while creating contact",
                google_account_email=self.google_account_email,
                error=str(e),
                status_code=e.resp.status,
            )
            raise e

    async def update_contact(
        self,
        resource_name: str,
        contact_data: dict[str, Any],
        etag: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing contact in Google People API.

        Uses optimistic concurrency control with ETags to detect conflicts.
        The ETag should be included in the contact_data's metadata.sources.etag field.
        If the contact has been modified by another client, Google will
        return a 400 error with "failedPrecondition" reason.

        Args:
            resource_name: Resource name of the contact (e.g., "people/c123456789")
            contact_data: Updated contact data in Google People API format
                         Should include metadata.sources with etag if conflict detection is needed
            etag: Optional ETag for optimistic concurrency control
                 If provided, will be added to contact_data metadata

        Returns:
            Updated contact data from Google People API including new etag

        Raises:
            HttpError: If API request fails (including 400 for conflicts)
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_service()

            logger.info(
                "Updating Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                has_etag=bool(etag),
            )

            # Add ETag to metadata if provided
            if etag:
                if "metadata" not in contact_data:
                    contact_data["metadata"] = {}
                if "sources" not in contact_data["metadata"]:
                    contact_data["metadata"]["sources"] = [{}]
                contact_data["metadata"]["sources"][0]["etag"] = etag

            # Build request parameters
            # Extract field names from contact_data (excluding metadata, resourceName, and etag)
            excluded_fields = {"metadata", "resourceName", "etag"}
            update_fields = [
                key for key in contact_data.keys() if key not in excluded_fields
            ]

            # Validate that we have fields to update
            if not update_fields:
                raise ValueError(
                    "No fields to update in contact_data. "
                    "contact_data must contain at least one field besides metadata, resourceName, or etag."
                )

            request_params = {
                "resourceName": resource_name,
                "updatePersonFields": ",".join(update_fields),
                "body": contact_data,
            }

            # Make the API call
            result = service.people().updateContact(**request_params).execute()

            logger.info(
                "Successfully updated Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                new_etag=result.get("etag"),
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            # Google returns 400 with "failedPrecondition" for ETag conflicts
            if e.resp.status == 400 and "failedPrecondition" in str(e):
                logger.warning(
                    "Conflict detected while updating Google contact (ETag mismatch)",
                    google_account_email=self.google_account_email,
                    resource_name=resource_name,
                    error=str(e),
                )
            else:
                logger.error(
                    "Google API error while updating contact",
                    google_account_email=self.google_account_email,
                    resource_name=resource_name,
                    error=str(e),
                    status_code=e.resp.status,
                )
            raise e
