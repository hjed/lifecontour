"""Integration tests for incremental sync flow using sync_token."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from transformer import GOOGLE_CONTACT_SYNC_SCOPE
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

        # Pre-create sync metadata so the delta contact is a known contact and is
        # therefore emitted as 'updated' (a brand-new contact would be 'created').
        await db_session.execute(
            text(
                """
                INSERT INTO sync_metadata
                    (user_id, internal_id, integration_source, external_id,
                     version_hash, sync_status, last_synced_at,
                     created_at, updated_at)
                VALUES
                    (:user_id, 1, 'google', 'people/updated123',
                     'etag_old', 'success', :now, :now, :now)
                """
            ),
            {"user_id": test_user, "now": now},
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
                personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,events,metadata,memberships,biographies",
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

    async def test_incremental_sync_emits_created_for_new_contacts(self, db_session):
        """Incremental delta emits 'created' for unseen contacts, 'updated' for known ones.

        Google's incremental delta returns contacts added remotely since the last
        sync as well as modified ones, so a contact with no sync_metadata must be
        emitted as contact.created (not contact.updated) to avoid the backend
        rejecting it with "Contact not found for update".
        """
        now = datetime.now(UTC)
        future_expiry = now + timedelta(hours=1)
        test_email = "incremental_created_test@example.com"
        test_user = "1"
        known_external_id = "people/known999"
        new_external_id = "people/new888"

        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        encrypted_token = fernet.encrypt(b"access_token")
        encrypted_refresh = fernet.encrypt(b"refresh_token")

        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES
                    (:user_id, :email, :token, :refresh, :expiry, :now, :now)
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
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_integration (user_id, google_account_email,
                                              contacts_sync_token, created_at, updated_at)
                VALUES
                    (:user_id, :email, :sync_token, :now, :now)
                ON CONFLICT (user_id, google_account_email) DO UPDATE SET
                    contacts_sync_token = EXCLUDED.contacts_sync_token
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "sync_token": "valid_sync_token_mixed",
                "now": now,
            },
        )
        # Only the "known" contact has sync_metadata; the "new" one does not.
        await db_session.execute(
            text(
                """
                INSERT INTO sync_metadata
                    (user_id, internal_id, integration_source, external_id,
                     version_hash, sync_status, last_synced_at,
                     created_at, updated_at)
                VALUES
                    (:user_id, 1, 'google', :external_id,
                     'etag_old', 'success', :now, :now, :now)
                """
            ),
            {"user_id": test_user, "external_id": known_external_id, "now": now},
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "test_job_mixed",
        }

        mock_connections = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "connections": [
                {"resourceName": known_external_id, "etag": "etag_known"},
                {"resourceName": new_external_id, "etag": "etag_new"},
            ],
            "nextSyncToken": "new_sync_token_mixed",
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

        assert result is not None
        assert result.get("contacts_created") == 1
        assert result.get("contacts_updated") == 1

        # The unseen contact must produce a contact.created outbox event.
        created_count = await db_session.execute(
            text(
                """
                SELECT count(*) FROM outbox_events
                WHERE event_type = 'contact.created'
                  AND (event_data::jsonb)->>'external_id' = :external_id
                """
            ),
            {"external_id": new_external_id},
        )
        assert created_count.scalar() == 1

        # The known contact must produce a contact.updated outbox event, naming
        # the Google scope so fields Google does not own keep their values.
        updated_scopes = await db_session.execute(
            text(
                """
                SELECT (event_data::jsonb)->'sync_scope' FROM outbox_events
                WHERE event_type = 'contact.updated'
                  AND (event_data::jsonb)->>'external_id' = :external_id
                """
            ),
            {"external_id": known_external_id},
        )
        assert [row[0] for row in updated_scopes] == [
            GOOGLE_CONTACT_SYNC_SCOPE.model_dump(mode="json")
        ]
