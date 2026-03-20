"""Integration tests for full sync flow."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from worker import sync_google_contacts


@pytest.mark.asyncio
class TestFullSyncIntegration:
    """Integration test for full sync flow handling."""

    async def test_full_sync_processes_all_pages_and_saves_token(self, db_session):
        """Test that sync_google_contacts does a full sync with multiple pages."""
        now = datetime.now(UTC)
        future_expiry = now + timedelta(hours=1)
        test_email = "full_sync_test@example.com"
        test_user = "2"

        # Encrypt the dummy tokens so GoogleAuthService can decrypt them
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        encrypted_token = fernet.encrypt(b"access_token")
        encrypted_refresh = fernet.encrypt(b"refresh_token")

        # Insert user authentication data
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
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "test_job_full_123",
        }

        # We mock googleapiclient.discovery.build instead of GoogleAPIClient
        # so that GoogleAuthService.get_access_token() is actually called and tested.
        call_count = {"count": 0}

        def mock_list_execute():
            if call_count["count"] == 0:
                call_count["count"] += 1
                return {
                    "connections": [
                        {"resourceName": "people/full_sync_1", "etag": "etag_1"}
                    ],
                    "nextPageToken": "page_2_token",
                }
            else:
                return {
                    "connections": [
                        {"resourceName": "people/full_sync_2", "etag": "etag_2"}
                    ],
                    "nextSyncToken": "new_sync_token_after_full_sync",
                }

        mock_connections = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.side_effect = mock_list_execute
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

            # Since sync_type is 'smart' and we supplied NO sync_token
            # it should have called list_connections twice
            assert mock_connections.list.call_count == 2

            # Result should show at least some metrics
            assert result is not None
            assert result.get("contacts_created") == 2
            assert result.get("contacts_updated") == 0

            # Validate that the token was updated in db
            result_db = await db_session.execute(
                text(
                    "SELECT contacts_sync_token FROM user_google_integration WHERE google_account_email = :email"
                ),
                {"email": test_email},
            )
            next_token = result_db.scalar()
            assert next_token == "new_sync_token_after_full_sync"

            # Check if outbox events were created
            result_outbox = await db_session.execute(
                text(
                    "SELECT count(*) FROM outbox_events WHERE (event_data::jsonb)->>'external_id' IN ('people/full_sync_1', 'people/full_sync_2')"
                )
            )
            outbox_count = result_outbox.scalar()
            assert outbox_count == 2
