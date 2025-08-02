"""
Google Contacts synchronization service.

Provides high-level operations for syncing contacts from Google Contacts
to our internal contact system.
"""

from datetime import UTC, datetime

import structlog
from googleapiclient.errors import HttpError
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Contact
from app.core.contacts.models.exceptions import (
    ContactValidationError,
    InvalidTagNameError,
)
from app.core.integrations.google_contacts.api_models import ListConnectionsResponse
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
