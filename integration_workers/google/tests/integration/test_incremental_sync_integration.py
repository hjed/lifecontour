"""Integration tests for incremental sync flow using sync_token."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from worker import sync_google_contacts


@pytest.mark.asyncio
class TestIncrementalSyncIntegration:
    """Integration test for incremental sync flow handling using sync_token."""

    async def test_incremental_sync_uses_contacts_sync_token(self, db_session):
        """Test that sync_google_contacts picks up contacts_sync_token and performs incremental sync."""
        now = datetime.now(UTC)
        future_expiry = now + timedelta(hours=1)
        test_email = "incremental_test@example.com"
        test_user = "1"

        # Encrypt the dummy tokens so GoogleAuthService can decrypt them
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        encrypted_token = fernet.encrypt(b"access_token")
        encrypted_refresh = fernet.encrypt(b"refresh_token")

        # Insert user authentication data (so auth works or bypasses)
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES
                    (:user_id, :email, :token, :refresh,
                     :expiry, :now, :now)
                ON CONFLICT (user_id, google_account_email) DO NOTHING
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "token": encrypted_token,
                "refresh": encrypted_refresh,
                "expiry": future_expiry,
                "now": now,
            },
        )

        # Insert user sync integration data
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_integration (user_id, google_account_email,
                                              contacts_sync_token,
                                              created_at, updated_at)
                VALUES
                    (:user_id, :email, :sync_token,
                     :now, :now)
                ON CONFLICT (user_id, google_account_email) DO UPDATE SET
                    contacts_sync_token = EXCLUDED.contacts_sync_token
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "sync_token": "valid_incremental_sync_token",
                "now": now,
            },
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "test_job_456",
        }

        # We mock googleapiclient.discovery.build instead of GoogleAPIClient
        # so that GoogleAuthService.get_access_token() is actually called and tested.
        mock_connections = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "connections": [
                {"resourceName": "people/updated123", "etag": "updated_etag"}
            ],
            "nextSyncToken": "new_sync_token_after_incremental",
            "nextPageToken": None,
        }
        mock_connections.list.return_value = mock_list

        mock_people = MagicMock()
        mock_people.connections.return_value = mock_connections

        mock_service = MagicMock()
        mock_service.people.return_value = mock_people

        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build", return_value=mock_service),
        ):
            result = await sync_google_contacts(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
                sync_type="smart",
            )

            # Since sync_type is 'smart' and we supplied a valid sync_token
            # it should have called list_connections with that specific sync_token
            mock_connections.list.assert_called_with(
                resourceName="people/me",
                pageSize=100,
                personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata,memberships,biographies",
                syncToken="valid_incremental_sync_token",
            )
            # Result should show at least some metrics
            assert result is not None
            assert result.get("contacts_updated") == 1

            # Validate that the token was updated in db
            result_db = await db_session.execute(
                text(
                    "SELECT contacts_sync_token FROM user_google_integration WHERE google_account_email = :email"
                ),
                {"email": test_email},
            )
            next_token = result_db.scalar()
            assert next_token == "new_sync_token_after_incremental"
