"""
Google OAuth repository for database operations.

Handles CRUD operations for Google OAuth tokens and account data
using SQLAlchemy Core with explicit SQL queries.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.google_oauth.exceptions import (
    GoogleAccountNotFoundError,
    GoogleOAuthTokenSaveError,
)
from app.core.integrations.google_oauth.models import GoogleAccount

logger = structlog.get_logger()


class GoogleOAuthRepository:
    """
    Repository for Google OAuth token storage operations.

    Uses SQLAlchemy Core with parameterized SQL queries for security.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        """
        Initialize repository with database connection.

        Args:
            connection: Async database connection
        """
        self._connection = connection

    async def get_accounts_for_user(self, user_id: str) -> list[GoogleAccount]:
        """
        Get all connected Google accounts for a user.

        Args:
            user_id: Site user identifier

        Returns:
            List of connected Google accounts
        """
        stmt = text("""
            SELECT id, user_id, google_account_email, expires_at,
                   created_at, updated_at
            FROM user_google_auth
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """)

        result = await self._connection.execute(stmt, {"user_id": user_id})
        rows = result.fetchall()

        return [
            GoogleAccount(
                id=row.id,
                user_id=row.user_id,
                email=row.google_account_email,
                expires_at=row.expires_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def get_account_by_email(
        self, user_id: str, email: str
    ) -> GoogleAccount | None:
        """
        Get a specific Google account by email.

        Args:
            user_id: Site user identifier
            email: Google account email

        Returns:
            GoogleAccount if found, None otherwise
        """
        stmt = text("""
            SELECT id, user_id, google_account_email, expires_at,
                   created_at, updated_at
            FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :email
        """)

        result = await self._connection.execute(
            stmt, {"user_id": user_id, "email": email}
        )
        row = result.fetchone()

        if not row:
            return None

        return GoogleAccount(
            id=row.id,
            user_id=row.user_id,
            email=row.google_account_email,
            expires_at=row.expires_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def save_tokens(
        self,
        user_id: str,
        email: str,
        encrypted_access_token: bytes,
        encrypted_refresh_token: bytes | None,
        expires_at: datetime,
    ) -> GoogleAccount:
        """
        Save or update Google OAuth tokens.

        Uses upsert pattern to handle both new and existing accounts.

        Args:
            user_id: Site user identifier
            email: Google account email
            encrypted_access_token: Fernet-encrypted access token
            encrypted_refresh_token: Fernet-encrypted refresh token
            expires_at: Token expiration timestamp

        Returns:
            Created or updated GoogleAccount
        """
        now = datetime.now(UTC)

        # Use PostgreSQL upsert (INSERT ... ON CONFLICT)
        stmt = text("""
            INSERT INTO user_google_auth (
                user_id, google_account_email, encrypted_access_token,
                encrypted_refresh_token, expires_at, created_at, updated_at
            ) VALUES (
                :user_id, :email, :access_token, :refresh_token,
                :expires_at, :created_at, :updated_at
            )
            ON CONFLICT (user_id, google_account_email)
            DO UPDATE SET
                encrypted_access_token = EXCLUDED.encrypted_access_token,
                encrypted_refresh_token = COALESCE(
                    EXCLUDED.encrypted_refresh_token,
                    user_google_auth.encrypted_refresh_token
                ),
                expires_at = EXCLUDED.expires_at,
                updated_at = EXCLUDED.updated_at
            RETURNING id, user_id, google_account_email, expires_at,
                      created_at, updated_at
        """)

        result = await self._connection.execute(
            stmt,
            {
                "user_id": user_id,
                "email": email,
                "access_token": encrypted_access_token,
                "refresh_token": encrypted_refresh_token,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise GoogleOAuthTokenSaveError(user_id=user_id, email=email)

        logger.info(
            "Saved Google OAuth tokens",
            user_id=user_id,
            email=email,
        )

        return GoogleAccount(
            id=row.id,
            user_id=row.user_id,
            email=row.google_account_email,
            expires_at=row.expires_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def delete_account(self, user_id: str, email: str) -> bool:
        """
        Delete a connected Google account.

        Args:
            user_id: Site user identifier
            email: Google account email to delete

        Returns:
            True if account was deleted, False if not found

        Raises:
            GoogleAccountNotFoundError: If account doesn't exist
        """
        stmt = text("""
            DELETE FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :email
            RETURNING id
        """)

        result = await self._connection.execute(
            stmt, {"user_id": user_id, "email": email}
        )
        deleted_row = result.fetchone()

        if not deleted_row:
            raise GoogleAccountNotFoundError(email)

        logger.info(
            "Deleted Google account",
            user_id=user_id,
            email=email,
        )

        return True

    async def account_exists(self, user_id: str, email: str) -> bool:
        """
        Check if a Google account exists for a user.

        Args:
            user_id: Site user identifier
            email: Google account email

        Returns:
            True if account exists
        """
        stmt = text("""
            SELECT 1 FROM user_google_auth
            WHERE user_id = :user_id AND google_account_email = :email
        """)

        result = await self._connection.execute(
            stmt, {"user_id": user_id, "email": email}
        )

        return result.fetchone() is not None
