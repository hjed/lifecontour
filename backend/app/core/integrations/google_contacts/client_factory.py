"""
Factory for creating Google Contacts API clients.

Provides a factory pattern for creating GoogleContactsAPIClient instances
with proper dependency injection while allowing per-request configuration.
"""

from app.core.integrations.google_contacts.client import GoogleContactsAPIClient
from app.core.integrations.google_contacts.service import GoogleAuthService


class GoogleContactsClientFactory:
    """Factory for creating Google Contacts API clients."""

    def __init__(
        self,
        auth_service: GoogleAuthService,
        google_client_id: str,
        google_client_secret: str,
    ) -> None:
        """
        Initialize the client factory.

        Args:
            auth_service: Google authentication service
            google_client_id: Google OAuth client ID
            google_client_secret: Google OAuth client secret
        """
        self.auth_service = auth_service
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret

    def create_client(self, google_account_email: str) -> GoogleContactsAPIClient:
        """
        Create a Google Contacts API client for a specific account.

        Args:
            google_account_email: Google account email to create client for

        Returns:
            GoogleContactsAPIClient: Configured client instance
        """
        return GoogleContactsAPIClient(
            auth_service=self.auth_service,
            google_account_email=google_account_email,
            google_client_id=self.google_client_id,
            google_client_secret=self.google_client_secret,
        )
