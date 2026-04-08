"""
Google Contacts API client for worker.

Simplified version of the core client adapted for worker environment.
Migrated from backend/app/core/integrations/google/client.py
"""

from typing import Any, cast

import structlog
from google.oauth2.credentials import Credentials as OAuth2Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth_service import GoogleAuthService, GoogleAuthTokensNotFoundError

logger = structlog.get_logger()


class GoogleAPIClient:
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
        self._people_service: Any | None = None
        self._calendar_service: Any | None = None

    async def _get_credentials(self) -> OAuth2Credentials:
        """Get OAuth2 credentials for Google API."""
        try:
            access_token = await self.auth_service.get_access_token(
                self.user_id, self.google_account_email
            )
            return OAuth2Credentials(
                token=access_token,
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
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

    async def _get_people_service(self) -> Any:
        """Get or create Google People API service with authentication."""
        if self._people_service is None:
            credentials = await self._get_credentials()
            self._people_service = build(
                "people", "v1", credentials=credentials, cache_discovery=False
            )
            logger.info(
                "Created Google People API service",
                google_account_email=self.google_account_email,
            )
        return self._people_service

    async def _get_calendar_service(self) -> Any:
        """Get or create Google Calendar API service with authentication."""
        if self._calendar_service is None:
            credentials = await self._get_credentials()
            self._calendar_service = build(
                "calendar", "v3", credentials=credentials, cache_discovery=False
            )
            logger.info(
                "Created Google Calendar API service",
                google_account_email=self.google_account_email,
            )
        return self._calendar_service

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
            service = await self._get_people_service()

            # Build request parameters
            request_params = {
                "resourceName": "people/me",
                "pageSize": min(page_size, 2000),  # Google's max limit
                "personFields": "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata,memberships,biographies",
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

    async def list_contact_groups(
        self,
        page_size: int = 1000,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        """
        List contact groups from Google People API.

        Args:
            page_size: Number of contact groups to return per page (max 1000)
            page_token: Token for pagination
            sync_token: Token for incremental sync

        Returns:
            Google People API response with contact groups data

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_people_service()

            request_params: dict[str, Any] = {
                "pageSize": min(page_size, 1000),
                "groupFields": "metadata,groupType,memberCount,name",
            }

            if page_token:
                request_params["pageToken"] = page_token
            if sync_token:
                request_params["syncToken"] = sync_token

            logger.info(
                "Fetching Google contact groups",
                google_account_email=self.google_account_email,
                page_size=page_size,
                has_page_token=bool(page_token),
                has_sync_token=bool(sync_token),
            )

            result = service.contactGroups().list(**request_params).execute()

            logger.info(
                "Successfully fetched Google contact groups",
                google_account_email=self.google_account_email,
                total_items=len(result.get("contactGroups", [])),
                next_page_token=result.get("nextPageToken"),
                next_sync_token=result.get("nextSyncToken"),
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            logger.error(
                "Google API error while fetching contact groups",
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
            service = await self._get_people_service()

            logger.info(
                "Fetching Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            result = (
                service.people()
                .get(
                    resourceName=resource_name,
                    personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata,memberships,biographies",
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
            service = await self._get_people_service()

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
            service = await self._get_people_service()

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

    async def create_contact_group(self, name: str) -> dict[str, Any]:
        """
        Create a new contact group in Google People API.

        Args:
            name: Display name for the new contact group

        Returns:
            Created contact group data including resourceName

        Raises:
            HttpError: If API request fails
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_people_service()

            logger.info(
                "Creating Google contact group",
                google_account_email=self.google_account_email,
                group_name=name,
            )

            result = (
                service.contactGroups()
                .create(body={"contactGroup": {"name": name}})
                .execute()
            )

            logger.info(
                "Successfully created Google contact group",
                google_account_email=self.google_account_email,
                group_name=name,
                resource_name=result.get("resourceName"),
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            logger.error(
                "Google API error while creating contact group",
                google_account_email=self.google_account_email,
                group_name=name,
                error=str(e),
                status_code=e.resp.status,
            )
            raise e

    async def update_contact_group(
        self, resource_name: str, name: str
    ) -> dict[str, Any]:
        """
        Update an existing contact group in Google People API.

        Args:
            resource_name: Resource name of the contact group
            name: New display name for the contact group

        Returns:
            Updated contact group data
        """
        try:
            service = await self._get_people_service()

            logger.info(
                "Updating Google contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                new_name=name,
            )

            # Need to fetch the group first to get the etag
            group_data = service.contactGroups().get(resourceName=resource_name).execute()
            etag = group_data.get("etag")

            update_body = {
                "contactGroup": {
                    "name": name,
                    "etag": etag
                }
            }

            result = (
                service.contactGroups()
                .update(
                    resourceName=resource_name,
                    updateContactGroupFields="name",
                    body=update_body,
                )
                .execute()
            )

            logger.info(
                "Successfully updated Google contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            return cast(dict[str, Any], result)

        except HttpError as e:
            if e.resp.status == 404:
                # Missing group; logging warning before re-raising. Callers or higher levels should recreate or handle.
                logger.warning(
                    "Contact group not found for update",
                    google_account_email=self.google_account_email,
                    resource_name=resource_name,
                )
            logger.error(
                "Google API error while updating contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                error=str(e),
                status_code=e.resp.status,
            )
            raise

    async def delete_contact_group(self, resource_name: str) -> None:
        """
        Delete a contact group from Google People API.

        Args:
            resource_name: Resource name of the contact group to delete
        """
        try:
            service = await self._get_people_service()

            logger.info(
                "Deleting Google contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            service.contactGroups().delete(
                resourceName=resource_name, deleteContacts=False
            ).execute()

            logger.info(
                "Successfully deleted Google contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

        except HttpError as e:
            if e.resp.status == 404:
                # Group already deleted, consider it a success
                logger.info(
                    "Contact group already deleted or not found",
                    google_account_email=self.google_account_email,
                    resource_name=resource_name,
                )
                return

            logger.error(
                "Google API error while deleting contact group",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                error=str(e),
                status_code=e.resp.status,
            )
            raise

    # Calendar API Operations

    async def list_calendars(
        self,
        page_token: str | None = None,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        """
        List calendars from Google Calendar API.
        """
        try:
            service = await self._get_calendar_service()
            request_params: dict[str, Any] = {"maxResults": 250}
            if page_token:
                request_params["pageToken"] = page_token
            if sync_token:
                request_params["syncToken"] = sync_token

            logger.info(
                "Fetching Google calendars",
                google_account_email=self.google_account_email,
            )
            result = service.calendarList().list(**request_params).execute()
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error("Error fetching Google calendars", error=str(e))
            raise e

    async def list_events(
        self,
        calendar_id: str = "primary",
        page_token: str | None = None,
        sync_token: str | None = None,
        time_min: str | None = None,
        updated_min: str | None = None,
    ) -> dict[str, Any]:
        """
        List events for a specific calendar.
        """
        try:
            service = await self._get_calendar_service()
            request_params = {
                "calendarId": calendar_id,
                "maxResults": 2500,
            }
            if page_token:
                request_params["pageToken"] = page_token
            if sync_token:
                request_params["syncToken"] = sync_token
            else:
                if time_min:
                    request_params["timeMin"] = time_min
                if updated_min:
                    request_params["updatedMin"] = updated_min

            logger.info(
                "Fetching Google Calendar events",
                google_account_email=self.google_account_email,
                calendar_id=calendar_id,
            )
            result = service.events().list(**request_params).execute()
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error("Error fetching events", error=str(e))
            raise e

    async def get_event(
        self, event_id: str, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Get a specific event."""
        try:
            service = await self._get_calendar_service()
            result = (
                service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            )
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error("Error fetching event", error=str(e))
            raise e

    async def create_event(
        self, event_data: dict[str, Any], calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Create a new event."""
        try:
            service = await self._get_calendar_service()
            result = (
                service.events()
                .insert(calendarId=calendar_id, body=event_data)
                .execute()
            )
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error("Error creating event", error=str(e))
            raise e

    async def update_event(
        self, event_id: str, event_data: dict[str, Any], calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Update an existing event."""
        try:
            service = await self._get_calendar_service()
            result = (
                service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event_data)
                .execute()
            )
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error("Error updating event", error=str(e))
            raise e

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete an event."""
        try:
            service = await self._get_calendar_service()
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        except HttpError as e:
            logger.error("Error deleting event", error=str(e))
            raise e

    async def watch_events(
        self,
        calendar_id: str,
        channel_id: str,
        webhook_url: str,
        ttl_seconds: int = 604800,  # 7 days default
    ) -> dict[str, Any]:
        """Register a push notification channel for calendar events.

        Args:
            calendar_id: Google Calendar ID to watch
            channel_id: Unique UUID for this notification channel
            webhook_url: HTTPS URL to receive notifications
            ttl_seconds: Channel expiration in seconds (max ~30 days)

        Returns:
            Google API response with channel metadata
        """
        try:
            service = await self._get_calendar_service()
            body = {
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_url,
                "params": {"ttl": str(ttl_seconds)},
            }
            result = service.events().watch(calendarId=calendar_id, body=body).execute()
            logger.info(
                "Registered calendar watch channel",
                calendar_id=calendar_id,
                channel_id=channel_id,
                resource_id=result.get("resourceId"),
                expiration=result.get("expiration"),
            )
            return cast(dict[str, Any], result)
        except HttpError as e:
            logger.error(
                "Error registering calendar watch",
                calendar_id=calendar_id,
                error=str(e),
            )
            raise

    async def stop_channel(self, channel_id: str, resource_id: str) -> None:
        """Stop a push notification channel.

        Args:
            channel_id: The channel UUID to stop
            resource_id: The resource ID from the watch response
        """
        try:
            service = await self._get_calendar_service()
            body = {
                "id": channel_id,
                "resourceId": resource_id,
            }
            service.channels().stop(body=body).execute()
            logger.info(
                "Stopped calendar watch channel",
                channel_id=channel_id,
                resource_id=resource_id,
            )
        except HttpError as e:
            logger.error(
                "Error stopping calendar watch channel",
                channel_id=channel_id,
                error=str(e),
            )
            raise
