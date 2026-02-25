"""Integration tests for incremental sync flow using sync_token."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import text

from worker import sync_google_contacts


@pytest.mark.asyncio
class TestIncrementalSyncIntegration:
    """Integration test for incremental sync flow handling using sync_token."""

    async def test_incremental_sync_uses_contacts_sync_token(
        self, db_session
    ):
        """Test that sync_google_contacts picks up contacts_sync_token and performs incremental sync."""
        now = datetime.now(timezone.utc)
        test_email = 'incremental_test@example.com'
        test_user = '1'

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
                "token": b"encrypted_token",
                "refresh": b"encrypted_refresh",
                "expiry": now,
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

        ctx = {"session_factory": mock_session_factory, "redis": None, "job_id": "test_job_456"}

        mock_auth_service = AsyncMock()
        mock_auth_service.get_access_token.return_value = "access_token"

        mock_contacts_client = AsyncMock()

        # We need the client to mock list_connections and handle multiple pages logic for robustness,
        # but incremental usually just returns one page of updates:
        mock_contacts_client.list_connections.return_value = {
            "connections": [
                {
                    "resourceName": "people/updated123",
                    "etag": "updated_etag"
                }
            ],
            "nextSyncToken": "new_sync_token_after_incremental",
            "nextPageToken": None
        }

        with patch("worker.GoogleAuthService", return_value=mock_auth_service), \
             patch("worker.GoogleContactsAPIClient", return_value=mock_contacts_client):

            result = await sync_google_contacts(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
                sync_type="smart",
            )

            # Since sync_type is 'smart' and we supplied a valid sync_token
            # it should have called list_connections with that specific sync_token
            mock_contacts_client.list_connections.assert_called_with(sync_token="valid_incremental_sync_token")
            # Result should show at least some metrics
            assert result is not None
            assert result.get("contacts_updated") == 1

            # Validate that the token was updated in db
            result_db = await db_session.execute(
                text("SELECT contacts_sync_token FROM user_google_integration WHERE google_account_email = :email"),
                {"email": test_email}
            )
            next_token = result_db.scalar()
            assert next_token == "new_sync_token_after_incremental"
