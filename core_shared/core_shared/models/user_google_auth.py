"""
User Google authentication SQLAlchemy model.

Stores encrypted Google OAuth tokens for users to enable Google API access.
Supports automatic token refresh and secure credential storage.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class UserGoogleAuth(Base):
    """
    Stores encrypted Google OAuth credentials for users.

    This model securely stores Google OAuth tokens with encryption to enable
    Google API access for integrations like Google Contacts. Features:
    1. Encrypted token storage using Fernet symmetric encryption
    2. Automatic token refresh support
    3. Multiple Google accounts per user support
    4. Per-user and per-account credential isolation
    5. Audit trail for security monitoring
    """

    __tablename__ = "user_google_auth"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "google_account_email",
            name="uq_user_google_auth_user_account",
        ),
    )

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # User association
    user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User ID from the main application's authentication system",
    )

    # Google account identification
    google_account_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Email address of the Google account for identification",
    )
    google_account_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Display name of the Google account",
    )

    # Encrypted OAuth tokens
    access_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Fernet-encrypted Google OAuth access token",
    )
    refresh_token_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Fernet-encrypted Google OAuth refresh token",
    )

    # Token metadata
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the access token expires (UTC)",
    )
    scope: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="OAuth scopes granted for this token",
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this auth record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
        comment="When this auth record was last updated",
    )

    def __repr__(self) -> str:
        return (
            f"<UserGoogleAuth(id={self.id}, "
            f"user_id='{self.user_id}', "
            f"google_account_email='{self.google_account_email}', "
            f"expires_at={self.expires_at})>"
        )
