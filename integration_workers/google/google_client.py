"""
Google Contacts API client for worker.

Simplified version of the core client adapted for worker environment.
Migrated from backend/app/core/integrations/google/client.py
"""

import json
from typing import Any, cast

import structlog
from google.oauth2.credentials import Credentials as OAuth2Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth_service import GoogleAuthService, GoogleAuthTokensNotFoundError

logger = structlog.get_logger()

# Google's reason code for "this event's type does not allow that change".
# A contact-linked birthday event accepts only colorId, summary and reminders;
# an event from Gmail accepts even less. See
# https://developers.google.com/workspace/calendar/api/guides/event-types
_EVENT_TYPE_RESTRICTION_REASON = "eventtyperestriction"


def is_event_type_restriction(error: HttpError) -> bool:
    """Return True if Google rejected the write because of the event's type.

    This is a **permanent** rejection: the event is one Google owns and
    derives (a birthday from Contacts, an event from Gmail), so no retry and
    no reshaping of the payload will make the same write land. Callers treat
    it as "this event is not ours to modify" rather than as a fault.

    Matched on the rendered error the way
    :meth:`GoogleAPIClient._is_etag_conflict` matches its own 400: the reason
    code travels in the error body, and ``HttpError.__str__`` is what renders
    the parsed ``errors`` details — reading ``error_details`` directly returns
    ``""`` until something has forced that parse.
    """
    if error.resp.status != 400:
        return False
    return _EVENT_TYPE_RESTRICTION_REASON in str(error).lower()


# The 403 reasons that mean "slow down" rather than "no". Everything else at
# 403 is a refusal: this set is the exception list precisely because a refusal
# we fail to recognise should stop the work rather than be retried forever.
# See https://developers.google.com/workspace/calendar/api/guides/errors
_TRANSIENT_403_REASONS = frozenset(
    {
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "quotaExceeded",
    }
)


def google_error_reasons(error: HttpError) -> set[str]:
    """Return the ``reason`` codes carried in a Google API error body.

    Returns an empty set when the body is missing, is not JSON, or carries no
    ``error.errors`` list — every caller has to cope with an unreadable body
    anyway, so this never raises.
    """
    content = error.content
    if not content:
        return set()

    try:
        decoded = content.decode() if isinstance(content, bytes) else str(content)
        payload: Any = json.loads(decoded)
        errors = payload["error"]["errors"]
    except Exception:  # noqa: BLE001 - an unreadable body is simply no reasons
        return set()

    if not isinstance(errors, list):
        return set()

    return {
        entry["reason"]
        for entry in errors
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str)
    }


def is_permission_denied(error: HttpError) -> bool:
    """Return True if ``error`` is a 403 that retrying cannot resolve.

    A 403 naming a rate or quota limit is transient and stays retryable. Any
    other 403 — including one whose body we cannot read — is a refusal: the
    account may not write to this calendar, or to this event. An unreadable
    403 is far more likely a permission answer than a quota one, and
    mis-classifying a quota 403 this way costs one skipped request rather
    than an endless retry loop.
    """
    if error.resp.status != 403:
        return False

    return not (google_error_reasons(error) & _TRANSIENT_403_REASONS)


# Statuses Google returns when a push notification channel no longer exists.
# Stopping such a channel has already achieved its purpose, so they are not
# failures: 404 is the expired-or-never-registered case, 410 the explicit "gone".
_CHANNEL_GONE_STATUSES: frozenset[int] = frozenset({404, 410})


class GoogleContactNotFoundError(Exception):
    """The Google contact a push targets no longer exists (People API 404).

    Raised by :meth:`GoogleAPIClient.update_contact` so callers can tell a
    contact deleted on Google's side apart from any other API failure without
    inspecting HTTP status codes. The original ``HttpError`` is the cause.
    """

    def __init__(self, resource_name: str) -> None:
        super().__init__(f"Google contact not found: {resource_name}")
        self.resource_name = resource_name


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
                "personFields": "names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,events,metadata,memberships,biographies",
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
                    personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,events,metadata,memberships,biographies",
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
        The ETag is sent in the top-level ``person.etag`` field — this is the
        person-level etag returned by Google's create/update responses (and
        stored as ``sync_metadata.version_hash``). It must NOT be placed under
        ``metadata.sources`` because the source etag is a different value.

        If the stored etag is stale (the contact changed on Google's side since
        our last sync), Google returns a 400 "failedPrecondition" error. In that
        case this method re-fetches the latest person to obtain a fresh etag and
        retries the update once.

        Args:
            resource_name: Resource name of the contact (e.g., "people/c123456789")
            contact_data: Updated contact data in Google People API format
            etag: Optional ETag for optimistic concurrency control
                 If provided, will be set on contact_data's top-level ``etag`` field

        Returns:
            Updated contact data from Google People API including new etag

        Raises:
            GoogleContactNotFoundError: If the contact no longer exists in
                Google (a 404 from the update, the etag refetch or the retry)
            HttpError: If API request fails (including 400 for conflicts)
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            return await self._update_contact_with_etag_retry(
                resource_name, contact_data, etag
            )
        except HttpError as e:
            if e.resp.status == 404:
                raise GoogleContactNotFoundError(resource_name) from e
            raise

    async def _update_contact_with_etag_retry(
        self,
        resource_name: str,
        contact_data: dict[str, Any],
        etag: str | None,
    ) -> dict[str, Any]:
        """Update a contact, refetching the etag and retrying once on conflict."""
        logger.info(
            "Updating Google contact",
            google_account_email=self.google_account_email,
            resource_name=resource_name,
            has_etag=bool(etag),
        )

        # ETag goes in the top-level person.etag field for optimistic
        # concurrency. The stored etag is the person-level etag from Google's
        # create/update response; it does NOT correspond to a source etag, so
        # it must not be placed under metadata.sources.
        if etag:
            contact_data["etag"] = etag

        try:
            return await self._execute_update_contact(resource_name, contact_data)
        except HttpError as e:
            if not self._is_etag_conflict(e):
                self._log_update_http_error(e, resource_name)
                raise e

            # Stale etag — re-fetch the latest person and retry once with the
            # fresh etag.
            self._log_update_http_error(e, resource_name)
            tried_etag = contact_data.get("etag")
            fresh = await self.get_person(resource_name)
            fresh_etag = fresh.get("etag")
            if not fresh_etag or fresh_etag == tried_etag:
                raise e

            logger.warning(
                "Refetched fresh etag after conflict, retrying contact update",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )
            contact_data["etag"] = fresh_etag
            try:
                return await self._execute_update_contact(resource_name, contact_data)
            except HttpError as retry_error:
                self._log_update_http_error(retry_error, resource_name)
                raise retry_error

    async def _execute_update_contact(
        self, resource_name: str, contact_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the update request and execute it against the People API."""
        service = await self._get_people_service()

        # Extract field names from contact_data (excluding metadata,
        # resourceName, and etag — none of which are updatable person fields).
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

        result = service.people().updateContact(**request_params).execute()

        logger.info(
            "Successfully updated Google contact",
            google_account_email=self.google_account_email,
            resource_name=resource_name,
            new_etag=result.get("etag"),
        )

        return cast(dict[str, Any], result)

    @staticmethod
    def _is_etag_conflict(error: HttpError) -> bool:
        """Return True if the error is a 400 etag/precondition conflict."""
        if error.resp.status != 400:
            return False
        message = str(error).lower()
        return "failedprecondition" in message or "etag" in message

    def _log_update_http_error(self, error: HttpError, resource_name: str) -> None:
        """Log a Google update error, distinguishing etag conflicts."""
        if error.resp.status == 400 and "failedPrecondition" in str(error):
            logger.warning(
                "Conflict detected while updating Google contact (ETag mismatch)",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                error=str(error),
            )
        else:
            logger.error(
                "Google API error while updating contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
                error=str(error),
                status_code=error.resp.status,
            )

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
            group_data = (
                service.contactGroups().get(resourceName=resource_name).execute()
            )
            etag = group_data.get("etag")

            update_body = {"contactGroup": {"name": name, "etag": etag}}

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

    async def delete_contact(self, resource_name: str) -> None:
        """Delete a contact from Google People API.

        Args:
            resource_name: Resource name of the contact (e.g., "people/c123456789")

        Raises:
            HttpError: If API request fails (404 is treated as already-deleted)
            GoogleAuthTokensNotFoundError: If authentication tokens are missing
        """
        try:
            service = await self._get_people_service()

            logger.info(
                "Deleting Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

            service.people().deleteContact(resourceName=resource_name).execute()

            logger.info(
                "Successfully deleted Google contact",
                google_account_email=self.google_account_email,
                resource_name=resource_name,
            )

        except HttpError as e:
            if e.resp.status == 404:
                # Contact already deleted, consider it a success
                logger.info(
                    "Contact already deleted or not found in Google",
                    google_account_email=self.google_account_email,
                    resource_name=resource_name,
                )
                return

            logger.error(
                "Google API error while deleting contact",
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
        time_max: str | None = None,
        single_events: bool = False,
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
            if single_events:
                request_params["singleEvents"] = single_events
            if page_token:
                request_params["pageToken"] = page_token

            if sync_token:
                request_params["syncToken"] = sync_token
            else:
                if time_min:
                    request_params["timeMin"] = time_min
                if time_max:
                    request_params["timeMax"] = time_max
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
        """Update an existing event using partial update (patch).

        Uses PATCH semantics so that only the fields present in event_data are
        modified.  Unspecified fields — notably ``attendees`` — are left
        untouched on the server, preventing accidental removal of invites.
        """
        try:
            service = await self._get_calendar_service()
            result = (
                service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=event_data)
                .execute()
            )
            return cast(dict[str, Any], result)
        except HttpError as e:
            # A type restriction is Google declining to be written to, not a
            # fault: it is re-raised so the caller can decide what the journal
            # should do about it, but it is not an error in this client.
            if is_event_type_restriction(e):
                logger.warning(
                    "Google rejected the event update: this event type is not "
                    "modifiable",
                    google_account_email=self.google_account_email,
                    calendar_id=calendar_id,
                    event_id=event_id,
                    error=str(e),
                )
                raise e
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

        Idempotent: channels expire on their own after their TTL, so a channel
        Google no longer knows about is already in the state this method exists
        to produce. Those responses (see ``_CHANNEL_GONE_STATUSES``) return
        normally rather than raising, which keeps the routine re-registration
        path from reporting an expired channel as a failure. Every other
        ``HttpError`` still propagates to the caller.

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
            if e.resp.status in _CHANNEL_GONE_STATUSES:
                logger.debug(
                    "Calendar watch channel was already stopped or expired",
                    channel_id=channel_id,
                    resource_id=resource_id,
                    status=e.resp.status,
                )
                return
            logger.error(
                "Error stopping calendar watch channel",
                channel_id=channel_id,
                error=str(e),
            )
            raise
