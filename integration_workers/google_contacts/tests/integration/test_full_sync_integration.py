"""Integration tests for full sync flow."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from worker import sync_google_contacts


@pytest.mark.asyncio
class TestFullSyncIntegration:
    """Integration test for full sync flow handling."""

    async def test_full_sync_processes_all_pages_and_saves_token(
        self, db_session
    ):
        """Test that sync_google_contacts does a full sync with multiple pages."""
        now = datetime.now(timezone.utc)
        test_email = 'full_sync_test@example.com'
        test_user = '2'

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
                "token": b"encrypted_token",
                "refresh": b"encrypted_refresh",
                "expiry": now,
                "now": now,
            },
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {"session_factory": mock_session_factory, "redis": None, "job_id": "test_job_full_123"}

        mock_auth_service = AsyncMock()
        mock_auth_service.get_access_token.return_value = "access_token"

        mock_contacts_client = AsyncMock()

        # We need the client to mock list_connections and handle multiple pages logic for robustness
        # First call returns a page with nextPageToken
        # Second call returns a page with nextSyncToken (simulation of completion)

        call_count = {"count": 0}

        async def mock_list_connections(*args, **kwargs):
            if call_count["count"] == 0:
                call_count["count"] += 1
                return {
                    "connections": [
                        {
                            "resourceName": "people/full_sync_1",
                            "etag": "etag_1"
                        }
                    ],
                    "nextPageToken": "page_2_token"
                }
            else:
                return {
                    "connections": [
                        {
                            "resourceName": "people/full_sync_2",
                            "etag": "etag_2"
                        }
                    ],
                    "nextSyncToken": "new_sync_token_after_full_sync"
                }

        mock_contacts_client.list_connections.side_effect = mock_list_connections

        with patch("worker.GoogleAuthService", return_value=mock_auth_service), \
             patch("worker.GoogleContactsAPIClient", return_value=mock_contacts_client):

            result = await sync_google_contacts(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
                sync_type="smart",
            )

            # Since sync_type is 'smart' and we supplied NO sync_token
            # it should have called list_connections twice
            assert mock_contacts_client.list_connections.call_count == 2

            # Result should show at least some metrics
            assert result is not None
            assert result.get("contacts_created") == 2

            # Validate that the token was updated in db
            result_db = await db_session.execute(
                text("SELECT contacts_sync_token FROM user_google_integration WHERE google_account_email = :email"),
                {"email": test_email}
            )
            next_token = result_db.scalar()
            assert next_token == "new_sync_token_after_full_sync"

            # Check if outbox events were created
            result_outbox = await db_session.execute(
                text("SELECT count(*) FROM outbox_events WHERE (event_data::jsonb)->>'external_id' IN ('people/full_sync_1', 'people/full_sync_2')")
            )
            outbox_count = result_outbox.scalar()
            assert outbox_count == 2
