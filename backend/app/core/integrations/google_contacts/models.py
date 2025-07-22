"""
Google Contacts integration models.

Contains SQLAlchemy models for storing Google OAuth credentials and sync state.
"""

from datetime import UTC, datetime

from core_shared.models.base import Base
from sqlalchemy import DateTime, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class UserGoogleAuth(Base):
    """
    Stores encrypted Google OAuth credentials for Google Contacts integration.

    Supports multiple Google accounts per user in a single-user system.
    Tokens are encrypted using Fernet encryption for security.
    """

    __tablename__ = "user_google_auth"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "google_account_email", name="uq_user_google_account"
        ),
    )

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # User identification (for single-user system, this will be "site-user")
    user_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="Site user identifier"
    )

    # Google account identification
    google_account_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Google account email address",
    )

    # Encrypted OAuth tokens (stored as binary data)
    encrypted_access_token: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, comment="Encrypted Google access token"
    )
    encrypted_refresh_token: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, comment="Encrypted Google refresh token"
    )

    # Token metadata
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Access token expiration timestamp",
    )

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Record creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment="Record last update timestamp",
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<UserGoogleAuth(id={self.id}, "
            f"user_id='{self.user_id}', "
            f"google_account_email='{self.google_account_email}', "
            f"expires_at={self.expires_at})>"
        )


class UserGoogleIntegration(Base):
    """
    Stores Google integration state for users.

    This model stores sync tokens and other integration metadata
    to enable incremental sync with Google services.
    """

    __tablename__ = "user_google_integration"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "google_account_email", name="uq_user_google_integration"
        ),
    )

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # User identification (for single-user system, this will be "site-user")
    user_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="Site user identifier"
    )

    # Google account identification
    google_account_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Google account email address",
    )

    # Sync tokens for incremental sync
    contacts_sync_token: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Google Contacts sync token for incremental sync",
    )

    # Last sync timestamps
    last_contacts_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful contacts sync timestamp",
    )

    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Record creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment="Record last update timestamp",
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<UserGoogleIntegration(id={self.id}, "
            f"user_id='{self.user_id}', "
            f"google_account_email='{self.google_account_email}', "
            f"last_contacts_sync_at={self.last_contacts_sync_at})>"
        )


# Constants for the single-user system
SITE_USER_ID = "site-user"
"""Constant user ID for the single-user system."""
