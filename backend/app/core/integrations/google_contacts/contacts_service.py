"""
Google Contacts synchronization service.

Provides high-level operations for syncing contacts from Google Contacts
to our internal contact system.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

import structlog
from googleapiclient.errors import HttpError
from pydantic import ValidationError
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Contact
from app.core.contacts.models.exceptions import (
    ContactValidationError,
    InvalidTagNameError,
)
from app.core.integrations.google_contacts.api_models import (
    GooglePerson,
    ListConnectionsResponse,
)
from app.core.integrations.google_contacts.client_factory import (
    GoogleContactsClientFactory,
)
from app.core.integrations.google_contacts.models import SITE_USER_ID
from app.core.integrations.google_contacts.service import (
    GoogleAuthTokensNotFoundError,
    TokenRefreshFailedError,
)
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer

logger = structlog.get_logger()


class GoogleContactsSyncError(Exception):
    """Raised when Google Contacts sync fails."""

    pass


class GoogleContactsService:
    """
    Service for synchronizing Google Contacts with our internal contact system.

    Provides methods for full sync and incremental sync of contacts from
    Google Contacts API to our internal Contact entities.
    """

    def __init__(
        self,
        connection: AsyncConnection,
        client_factory: GoogleContactsClientFactory,
        transformer: GoogleContactTransformer,
    ) -> None:
        """
        Initialize Google Contacts service.

        Args:
            connection: Database connection for storing sync state
            client_factory: Factory for creating Google Contacts API clients
            transformer: Contact data transformer (singleton)
        """
        self.connection = connection
        self.client_factory = client_factory
        self.transformer = transformer

    async def full_sync(
        self, google_account_email: str
    ) -> tuple[list[Contact], str | None]:
        """
        Perform a full sync of contacts from Google Contacts.

        This method fetches all contacts from Google Contacts API and transforms
        them to our internal Contact entities. It handles pagination automatically
        and returns the complete list of contacts along with the next sync token.

        Args:
            google_account_email: Google account email to sync contacts from

        Returns:
            Tuple of (list of Contact entities, next sync token for incremental sync)

        Raises:
            GoogleContactsSyncError: If sync fails due to API or authentication errors
        """
        logger.info(
            "Starting full Google Contacts sync",
            google_account_email=google_account_email,
        )

        try:
            # Create API client for this specific Google account
            client = self.client_factory.create_client(google_account_email)

            # Fetch all contacts with pagination
            all_contacts = []
            next_page_token = None
            total_fetched = 0
            page_count = 0

            while True:
                page_count += 1
                logger.debug(
                    "Fetching contacts page",
                    google_account_email=google_account_email,
                    page=page_count,
                    page_token=next_page_token,
                )

                # Fetch page of contacts
                response_data = await client.list_connections(
                    page_size=100,  # Google's recommended page size
                    page_token=next_page_token,
                    sync_token=None,  # Full sync doesn't use sync token
                )

                # Parse response
                response = ListConnectionsResponse(**response_data)

                # Transform Google contacts to our internal format
                page_contacts = []
                for google_person in response.connections:
                    try:
                        contact = self.transformer.transform_person(google_person)
                        page_contacts.append(contact)
                    except (
                        ValueError,
                        InvalidTagNameError,
                        ContactValidationError,
                    ) as e:
                        logger.warning(
                            "Failed to transform Google contact due to validation error",
                            google_account_email=google_account_email,
                            resource_name=google_person.resource_name,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        # Continue with other contacts instead of failing completely
                        continue
                    except ValidationError as e:
                        logger.warning(
                            "Failed to transform Google contact due to Pydantic validation error",
                            google_account_email=google_account_email,
                            resource_name=google_person.resource_name,
                            error=str(e),
                            validation_errors=e.errors(),
                        )
                        # Continue with other contacts instead of failing completely
                        continue

                all_contacts.extend(page_contacts)
                total_fetched += len(response.connections)

                logger.debug(
                    "Processed contacts page",
                    google_account_email=google_account_email,
                    page=page_count,
                    page_contacts=len(page_contacts),
                    total_contacts=len(all_contacts),
                    total_fetched=total_fetched,
                )

                # Check if there are more pages
                next_page_token = response.next_page_token
                if not next_page_token:
                    break

            # Update sync state in database
            next_sync_token = response.next_sync_token
            await self._update_sync_state(google_account_email, next_sync_token)

            logger.info(
                "Completed full Google Contacts sync",
                google_account_email=google_account_email,
                total_contacts=len(all_contacts),
                total_fetched=total_fetched,
                pages_processed=page_count,
                next_sync_token=bool(next_sync_token),
            )

            return all_contacts, next_sync_token

        except HttpError as e:
            logger.error(
                "Google API error during contacts sync",
                google_account_email=google_account_email,
                error=str(e),
                status_code=e.resp.status if hasattr(e, "resp") else None,
            )
            raise GoogleContactsSyncError(
                f"Google API error while syncing contacts for {google_account_email}: {str(e)}"
            ) from e
        except (GoogleAuthTokensNotFoundError, TokenRefreshFailedError) as e:
            logger.error(
                "Google authentication error during contacts sync",
                google_account_email=google_account_email,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise GoogleContactsSyncError(
                f"Authentication error while syncing contacts for {google_account_email}: {str(e)}"
            ) from e
        except ValidationError as e:
            logger.error(
                "Data validation error during contacts sync",
                google_account_email=google_account_email,
                error=str(e),
                validation_errors=e.errors(),
            )
            raise GoogleContactsSyncError(
                f"Data validation error while syncing contacts for {google_account_email}: {str(e)}"
            ) from e

    async def incremental_sync(
        self, google_account_email: str, sync_token: str
    ) -> tuple[list[Contact], str | None]:
        """
        Perform incremental sync of contacts from Google Contacts using sync token.

        This method uses Google's sync token to efficiently fetch only contacts that
        have changed since the last sync. It handles created, updated, and deleted
        contacts appropriately.

        Args:
            google_account_email: Google account email to sync contacts from
            sync_token: Sync token from previous sync for incremental updates

        Returns:
            Tuple of (list of Contact entities, next sync token for future incremental sync)

        Raises:
            GoogleContactsSyncError: If sync fails due to API or authentication errors
        """
        logger.info(
            "Starting incremental Google Contacts sync",
            google_account_email=google_account_email,
            sync_token=sync_token[:20] + "..." if len(sync_token) > 20 else sync_token,
        )

        try:
            # Create API client
            client = self.client_factory.create_client(google_account_email)

            # Fetch incremental changes using sync token
            try:
                response = await client.list_connections(sync_token=sync_token)
            except HttpError as e:
                if e.resp.status == 410:  # Gone - sync token expired
                    logger.warning(
                        "Sync token expired, falling back to full sync",
                        google_account_email=google_account_email,
                        sync_token=sync_token[:20] + "..."
                        if len(sync_token) > 20
                        else sync_token,
                    )
                    return await self.full_sync(google_account_email)
                raise  # Re-raise other HTTP errors

            # Parse response - keep raw data for processing
            google_persons = response.get("connections", [])
            next_sync_token = response.get("nextSyncToken")

            logger.info(
                "Fetched incremental contacts from Google API",
                google_account_email=google_account_email,
                contact_count=len(google_persons),
                has_next_sync_token=bool(next_sync_token),
            )

            # Process contacts (handle creates, updates, and deletes)
            contacts = await self._process_incremental_contacts(
                google_account_email, google_persons
            )

            # Update sync state
            await self._update_sync_state(google_account_email, next_sync_token)

            logger.info(
                "Completed incremental Google Contacts sync",
                google_account_email=google_account_email,
                processed_contacts=len(contacts),
                next_sync_token=next_sync_token[:20] + "..."
                if next_sync_token and len(next_sync_token) > 20
                else next_sync_token,
            )

            return contacts, next_sync_token

        except HttpError as e:
            logger.error(
                "HTTP error during incremental contacts sync",
                google_account_email=google_account_email,
                error_code=e.resp.status,
                error_message=str(e),
            )
            raise GoogleContactsSyncError(
                f"HTTP error during incremental sync for {google_account_email}: {str(e)}"
            ) from e
        except ValidationError as e:
            logger.error(
                "Data validation error during incremental contacts sync",
                google_account_email=google_account_email,
                error=str(e),
                validation_errors=e.errors(),
            )
            raise GoogleContactsSyncError(
                f"Data validation error during incremental sync for {google_account_email}: {str(e)}"
            ) from e

    async def _update_sync_state(
        self, google_account_email: str, sync_token: str | None
    ) -> None:
        """
        Update the sync state in the database.

        Args:
            google_account_email: Google account email
            sync_token: Sync token for incremental sync
        """
        now = datetime.now(UTC)

        # Upsert sync state record
        stmt = text("""
            INSERT INTO user_google_integration
                (user_id, google_account_email, contacts_sync_token, last_contacts_sync_at, created_at, updated_at)
            VALUES
                (:user_id, :email, :sync_token, :sync_time, :now, :now)
            ON CONFLICT (user_id, google_account_email)
            DO UPDATE SET
                contacts_sync_token = EXCLUDED.contacts_sync_token,
                last_contacts_sync_at = EXCLUDED.last_contacts_sync_at,
                updated_at = EXCLUDED.updated_at
        """)

        await self.connection.execute(
            stmt,
            {
                "user_id": SITE_USER_ID,
                "email": google_account_email,
                "sync_token": sync_token,
                "sync_time": now,
                "now": now,
            },
        )

        logger.debug(
            "Updated Google Contacts sync state",
            google_account_email=google_account_email,
            sync_token=bool(sync_token),
            sync_time=now,
        )

    async def get_last_sync_token(self, google_account_email: str) -> str | None:
        """
        Get the last sync token for incremental sync.

        Args:
            google_account_email: Google account email

        Returns:
            Last sync token or None if no previous sync
        """
        stmt = text("""
            SELECT contacts_sync_token
            FROM user_google_integration
            WHERE user_id = :user_id AND google_account_email = :email
        """)

        result = await self.connection.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        row = result.fetchone()

        return row.contacts_sync_token if row else None

    async def get_last_sync_time(self, google_account_email: str) -> datetime | None:
        """
        Get the last sync time.

        Args:
            google_account_email: Google account email

        Returns:
            Last sync timestamp or None if no previous sync
        """
        stmt = text("""
            SELECT last_contacts_sync_at
            FROM user_google_integration
            WHERE user_id = :user_id AND google_account_email = :email
        """)

        result = await self.connection.execute(
            stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
        )
        row = result.fetchone()

        return row.last_contacts_sync_at if row else None

    async def save_contacts_with_metadata(
        self,
        google_account_email: str,
        contacts: list[Contact],
        google_persons: list[dict[str, Any]],
    ) -> None:
        """
        Save contacts and their sync metadata with idempotent operations.

        This method implements the core persistence logic for both full sync and
        incremental sync. It uses version hashing (ETags) to ensure idempotent
        operations - contacts are only updated if their version hash has changed.

        Args:
            google_account_email: Google account email for sync tracking
            contacts: List of Contact entities to save
            google_persons: Corresponding Google Person API data for version hashing

        Raises:
            GoogleContactsSyncError: If persistence operations fail
        """
        if len(contacts) != len(google_persons):
            raise GoogleContactsSyncError(
                f"Mismatch between contacts ({len(contacts)}) and Google persons ({len(google_persons)})"
            )

        logger.info(
            "Starting persistence of contacts with metadata",
            google_account_email=google_account_email,
            contact_count=len(contacts),
        )

        try:
            # Get existing sync metadata for all external IDs
            external_ids = [person.get("resourceName", "") for person in google_persons]
            existing_metadata = await self._get_existing_sync_metadata(external_ids)

            # Process each contact with its corresponding Google person data
            for contact, google_person in zip(contacts, google_persons, strict=True):
                await self._save_single_contact_with_metadata(
                    contact, google_person, existing_metadata
                )

            logger.info(
                "Successfully persisted contacts with metadata",
                google_account_email=google_account_email,
                contact_count=len(contacts),
            )

        except Exception as e:
            logger.error(
                "Failed to persist contacts with metadata",
                google_account_email=google_account_email,
                error=str(e),
            )
            raise GoogleContactsSyncError(
                f"Failed to persist contacts for {google_account_email}: {str(e)}"
            ) from e

    async def _get_existing_sync_metadata(
        self, external_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Get existing sync metadata for external IDs.

        Args:
            external_ids: List of external IDs to look up

        Returns:
            Dictionary mapping external_id to metadata dict
        """
        if not external_ids:
            return {}

        # Use SQLAlchemy's expanding bindparam for safe IN clause construction
        stmt = text("""
            SELECT internal_id, external_id, version_hash, sync_status, last_synced_at
            FROM sync_metadata
            WHERE integration_source = 'google_contacts'
            AND external_id IN :external_ids
        """).bindparams(bindparam("external_ids", expanding=True))

        result = await self.connection.execute(stmt, {"external_ids": external_ids})
        rows = result.fetchall()

        return {
            row.external_id: {
                "internal_id": row.internal_id,
                "version_hash": row.version_hash,
                "sync_status": row.sync_status,
                "last_synced_at": row.last_synced_at,
            }
            for row in rows
        }

    async def _save_single_contact_with_metadata(
        self,
        contact: Contact,
        google_person: dict[str, Any],
        existing_metadata: dict[str, dict[str, Any]],
    ) -> None:
        """
        Save a single contact with its sync metadata using idempotent operations.

        Args:
            contact: Contact entity to save
            google_person: Google Person API data
            existing_metadata: Dictionary of existing sync metadata
        """
        external_id = google_person.get("resourceName", "")
        current_version_hash = self._create_version_hash(google_person)

        # Check if we have existing metadata for this contact
        existing = existing_metadata.get(external_id)

        if existing and existing["version_hash"] == current_version_hash:
            # Contact hasn't changed, skip processing (idempotent)
            logger.debug(
                "Skipping contact - no changes detected",
                external_id=external_id,
                version_hash=current_version_hash,
            )
            return

        # Contact is new or has changes - save/update it
        if existing:
            # Update existing contact
            contact.id = existing["internal_id"]
            await self._update_contact_in_database(contact)
            await self._update_sync_metadata(external_id, current_version_hash)
            logger.debug(
                "Updated existing contact",
                external_id=external_id,
                internal_id=existing["internal_id"],
                version_hash=current_version_hash,
            )
        else:
            # Create new contact
            saved_contact = await self._create_contact_in_database(contact)
            if saved_contact.id is None:
                raise GoogleContactsSyncError(
                    "Failed to create contact - no ID assigned"
                )
            await self._create_sync_metadata(
                saved_contact.id, external_id, current_version_hash
            )
            logger.debug(
                "Created new contact",
                external_id=external_id,
                internal_id=saved_contact.id,
                version_hash=current_version_hash,
            )

    def _create_version_hash(self, google_person: dict[str, Any]) -> str:
        """
        Create version hash from Google Person data.

        Uses ETag if available, otherwise creates hash from person data.
        This enables idempotent operations by detecting changes.

        Args:
            google_person: Google Person API data

        Returns:
            Version hash string (ETag or SHA-256 hash)
        """
        # Use ETag if available (preferred for Google API)
        etag = google_person.get("etag")
        if etag is not None:
            return str(etag)

        # Fallback: create hash from person data
        # Sort keys for consistent hashing
        person_str = str(sorted(google_person.items()))
        # Truncate to 32 chars (128 bits) - sufficient for change detection
        # Full SHA-256 not needed since this is only for version comparison, not security
        return hashlib.sha256(person_str.encode()).hexdigest()[:32]

    async def _create_contact_in_database(self, contact: Contact) -> Contact:
        """
        Create a new contact in the database.

        Args:
            contact: Contact entity to create

        Returns:
            Contact with assigned ID and timestamps
        """
        # For now, we'll use a simple SQL insert
        # In a full implementation, this would use the ContactRepository
        stmt = text("""
            INSERT INTO contacts (first_name, last_name, middle_name, nick_name, is_favourite)
            VALUES (:first_name, :last_name, :middle_name, :nick_name, :is_favourite)
            RETURNING id, created_at, updated_at
        """)

        result = await self.connection.execute(
            stmt,
            {
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "middle_name": contact.middle_name,
                "nick_name": contact.nick_name,
                "is_favourite": contact.is_favourite,
            },
        )

        row = result.fetchone()
        if not row:
            raise GoogleContactsSyncError("Failed to create contact in database")

        contact.id = row.id
        contact.created_at = row.created_at
        contact.updated_at = row.updated_at

        return contact

    async def _update_contact_in_database(self, contact: Contact) -> None:
        """
        Update an existing contact in the database.

        Args:
            contact: Contact entity to update (must have ID)
        """
        if not contact.id:
            raise GoogleContactsSyncError("Cannot update contact without ID")

        stmt = text("""
            UPDATE contacts
            SET first_name = :first_name,
                last_name = :last_name,
                middle_name = :middle_name,
                nick_name = :nick_name,
                is_favourite = :is_favourite,
                updated_at = now()
            WHERE id = :contact_id
            RETURNING updated_at
        """)

        result = await self.connection.execute(
            stmt,
            {
                "contact_id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "middle_name": contact.middle_name,
                "nick_name": contact.nick_name,
                "is_favourite": contact.is_favourite,
            },
        )

        row = result.fetchone()
        if not row:
            raise GoogleContactsSyncError(f"Failed to update contact {contact.id}")

        contact.updated_at = row.updated_at

    async def _create_sync_metadata(
        self, internal_id: int, external_id: str, version_hash: str
    ) -> None:
        """
        Create sync metadata for a new contact.

        Args:
            internal_id: Internal contact ID
            external_id: External Google contact ID
            version_hash: Version hash (ETag)
        """
        now = datetime.now(UTC)

        stmt = text("""
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id, version_hash,
                 sync_status, last_synced_at, retry_count, created_at, updated_at)
            VALUES
                (:internal_id, 'google_contacts', :external_id, :version_hash,
                 'success', :now, 0, :now, :now)
        """)

        await self.connection.execute(
            stmt,
            {
                "internal_id": internal_id,
                "external_id": external_id,
                "version_hash": version_hash,
                "now": now,
            },
        )

    async def _update_sync_metadata(self, external_id: str, version_hash: str) -> None:
        """
        Update sync metadata for an existing contact.

        Args:
            external_id: External Google contact ID
            version_hash: New version hash (ETag)
        """
        now = datetime.now(UTC)

        stmt = text("""
            UPDATE sync_metadata
            SET version_hash = :version_hash,
                sync_status = 'success',
                last_synced_at = :now,
                updated_at = :now,
                retry_count = 0,
                error_message = NULL
            WHERE integration_source = 'google_contacts'
            AND external_id = :external_id
        """)

        result = await self.connection.execute(
            stmt,
            {
                "external_id": external_id,
                "version_hash": version_hash,
                "now": now,
            },
        )

        if result.rowcount == 0:
            raise GoogleContactsSyncError(
                f"Failed to update sync metadata for {external_id}"
            )

    async def _process_incremental_contacts(
        self, google_account_email: str, google_persons: list[dict[str, Any]]
    ) -> list[Contact]:
        """
        Process incremental contact changes (creates, updates, deletes).

        Args:
            google_account_email: Google account email
            google_persons: List of Google Person data from incremental sync

        Returns:
            List of processed Contact entities
        """
        contacts = []

        for google_person_data in google_persons:
            # Check if this is a deleted contact
            if google_person_data.get("metadata", {}).get("deleted", False):
                await self._handle_deleted_contact(google_person_data)
                continue

            # Transform and save/update contact
            try:
                # Convert to Pydantic model for transformer
                google_person = GooglePerson.model_validate(google_person_data)
                contact = self.transformer.transform_person(google_person)

                # Save contact with metadata (handles both new and updated contacts)
                await self.save_contacts_with_metadata(
                    google_account_email, [contact], [google_person_data]
                )

                contacts.append(contact)

            except Exception as e:
                logger.error(
                    "Failed to process incremental contact",
                    google_account_email=google_account_email,
                    resource_name=google_person_data.get("resourceName", "unknown"),
                    error=str(e),
                )
                # Continue processing other contacts
                continue

        return contacts

    async def _handle_deleted_contact(self, google_person: dict[str, Any]) -> None:
        """
        Handle a deleted contact from incremental sync.

        For now, we'll implement soft deletion by removing the sync metadata.
        In a full implementation, this might set a deleted flag on the contact.

        Args:
            google_person: Google Person data with deleted=True
        """
        external_id = google_person.get("resourceName", "")

        logger.info(
            "Handling deleted contact",
            external_id=external_id,
        )

        # Remove sync metadata for deleted contact
        stmt = text("""
            DELETE FROM sync_metadata
            WHERE integration_source = 'google_contacts'
            AND external_id = :external_id
        """)

        result = await self.connection.execute(stmt, {"external_id": external_id})

        if result.rowcount > 0:
            logger.info(
                "Removed sync metadata for deleted contact",
                external_id=external_id,
            )
        else:
            logger.warning(
                "No sync metadata found for deleted contact",
                external_id=external_id,
            )
