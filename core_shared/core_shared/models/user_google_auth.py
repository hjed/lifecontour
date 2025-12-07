"""
UserGoogleAuth model for storing encrypted Google OAuth tokens.

This model is used by both the main application (for OAuth flow) and
integration workers (for token refresh and API calls).
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base

# SQL function constant to avoid duplication
SQL_NOW_FUNCTION = "now()"


class UserGoogleAuth(Base):
    """
    Stores encrypted Google OAuth tokens for a user's connected Google accounts.

    Supports multiple Google accounts per user. Tokens are encrypted at rest
    using Fernet symmetric encryption.

    Used by:
    - Main API: OAuth flow (authorization, callback, token storage)
    - Workers: Token retrieval and refresh for API calls
    """

    __tablename__ = "user_google_auth"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # User and account identification
    user_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Site user identifier",
    )
    google_account_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Google account email address",
    )

    # Encrypted tokens (stored as binary for Fernet encryption)
    encrypted_access_token: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Fernet-encrypted Google access token",
    )
    encrypted_refresh_token: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        comment="Fernet-encrypted Google refresh token",
    )

    # Token expiration
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Access token expiration timestamp",
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(SQL_NOW_FUNCTION),
        comment="When this auth record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text(SQL_NOW_FUNCTION),
        onupdate=text(SQL_NOW_FUNCTION),
        comment="When this auth record was last updated",
    )

    # Indexes and constraints
    __table_args__ = (
        # Unique constraint: one token set per user per Google account
        Index(
            "uq_user_google_account",
            "user_id",
            "google_account_email",
            unique=True,
        ),
        # Index for user lookup
        Index("idx_user_google_auth_user_id", "user_id"),
        # Index for email lookup
        Index("idx_user_google_auth_email", "google_account_email"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserGoogleAuth(id={self.id}, "
            f"user_id='{self.user_id}', "
            f"google_account_email='{self.google_account_email}')>"
        )
