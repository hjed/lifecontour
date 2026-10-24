"""Integration tests for full sync flow."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from synced_entries import raw_entry_key
from transformer import GOOGLE_CONTACT_SYNC_SCOPE
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

            # Both the event and the contact it carries name the job's user
            result_owners = await db_session.execute(
                text(
                    """
                    SELECT (event_data::jsonb)->>'user_id',
                           (event_data::jsonb)->'contact_data'->>'user_id'
                    FROM outbox_events
                    WHERE (event_data::jsonb)->>'external_id'
                          IN ('people/full_sync_1', 'people/full_sync_2')
                    """
                )
            )
            assert result_owners.all() == [(test_user, test_user)] * 2

            # Each event names the Google scope, so fields Google does not own
            # (nickname, avatar, other date types) keep their local values.
            result_scopes = await db_session.execute(
                text(
                    """
                    SELECT (event_data::jsonb)->'sync_scope'
                    FROM outbox_events
                    WHERE (event_data::jsonb)->>'external_id'
                          IN ('people/full_sync_1', 'people/full_sync_2')
                    """
                )
            )
            expected_scope = GOOGLE_CONTACT_SYNC_SCOPE.model_dump(mode="json")
            assert [row[0] for row in result_scopes] == [expected_scope] * 2

            # A full sync re-applies every person, even one whose etag is
            # unchanged, so a field Google newly owns reaches every contact.
            result_force = await db_session.execute(
                text(
                    """
                    SELECT (event_data::jsonb)->'force_apply'
                    FROM outbox_events
                    WHERE (event_data::jsonb)->>'external_id'
                          IN ('people/full_sync_1', 'people/full_sync_2')
                    """
                )
            )
            assert [row[0] for row in result_force] == [True, True]

    async def test_full_sync_gives_a_countryless_address_the_default_country(
        self, db_session
    ) -> None:
        """The import reads the syncing user's default country (#1820)."""
        now = datetime.now(UTC)
        test_email = "default_country_sync@example.com"
        test_user = "1820"
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES (:user_id, :email, :token, :refresh, :expiry, :now, :now)
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "token": fernet.encrypt(b"access_token"),
                "refresh": fernet.encrypt(b"refresh_token"),
                "expiry": now + timedelta(hours=1),
                "now": now,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO user_settings (user_id, default_country) "
                "VALUES (:user_id, 'NZ')"
            ),
            {"user_id": test_user},
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "connections": [
                {
                    "resourceName": "people/default_country_1",
                    "etag": "etag_1",
                    "names": [{"givenName": "Kiri", "metadata": {"primary": True}}],
                    "addresses": [{"streetAddress": "1 Queen St", "city": "Auckland"}],
                }
            ],
            "nextSyncToken": "token_after_default_country_sync",
        }
        mock_service = MagicMock()
        mock_service.people.return_value.connections.return_value.list.return_value = (
            mock_list
        )

        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build", return_value=mock_service),
        ):
            await sync_google_contacts(
                ctx={
                    "session_factory": mock_session_factory,
                    "redis": None,
                    "job_id": "test_job_default_country",
                },
                google_account_email=test_email,
                user_id=test_user,
                sync_type="full",
            )

        addresses = await db_session.execute(
            text(
                """
                SELECT (event_data::jsonb)->'contact_data'->'addresses',
                       (event_data::jsonb)->>'address_fallback_country',
                       (event_data::jsonb)->'synced_entries'
                FROM outbox_events
                WHERE (event_data::jsonb)->>'external_id' = 'people/default_country_1'
                """
            )
        )
        [(contact_addresses, fallback, synced)] = addresses.all()
        assert [(a["street_line_1"], a["country_code"]) for a in contact_addresses] == [
            ("1 Queen St", "NZ")
        ]
        # The backend records it on the link, for the push merge to own it.
        assert fallback == "NZ"
        # So is the base the next push merges against, the address keyed in
        # the country it was imported with (#1861).
        assert synced == {
            "emailAddresses": [],
            "phoneNumbers": [],
            "addresses": [
                raw_entry_key(
                    "addresses",
                    {"streetAddress": "1 Queen St", "city": "Auckland"},
                    "NZ",
                )
            ],
            "birthdays": [],
        }

    async def test_full_sync_reports_an_address_whose_region_is_unrecognised(
        self, db_session
    ) -> None:
        """Skipped from the contact, carried on the event for review (#1820)."""
        now = datetime.now(UTC)
        test_email = "skipped_region_sync@example.com"
        test_user = "1820-skip"
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES (:user_id, :email, :token, :refresh, :expiry, :now, :now)
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "token": fernet.encrypt(b"access_token"),
                "refresh": fernet.encrypt(b"refresh_token"),
                "expiry": now + timedelta(hours=1),
                "now": now,
            },
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "connections": [
                {
                    "resourceName": "people/skipped_region_1",
                    "etag": "etag_1",
                    "names": [{"givenName": "Kiri", "metadata": {"primary": True}}],
                    "addresses": [
                        {
                            "streetAddress": "10 Downing St",
                            "region": "London",
                            "countryCode": "AU",
                        },
                        {
                            "streetAddress": "1 George St",
                            "region": "new south wales",
                            "countryCode": "AU",
                        },
                    ],
                }
            ],
            "nextSyncToken": "token_after_skipped_region_sync",
        }
        mock_service = MagicMock()
        mock_service.people.return_value.connections.return_value.list.return_value = (
            mock_list
        )

        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build", return_value=mock_service),
        ):
            await sync_google_contacts(
                ctx={
                    "session_factory": mock_session_factory,
                    "redis": None,
                    "job_id": "test_job_skipped_region",
                },
                google_account_email=test_email,
                user_id=test_user,
                sync_type="full",
            )

        rows = await db_session.execute(
            text(
                """
                SELECT (event_data::jsonb)->'contact_data'->'addresses',
                       (event_data::jsonb)->'skipped_addresses'
                FROM outbox_events
                WHERE (event_data::jsonb)->>'external_id' = 'people/skipped_region_1'
                """
            )
        )
        [(addresses, skipped)] = rows.all()
        assert [(a["street_line_1"], a["region"]) for a in addresses] == [
            ("1 George St", "NSW")
        ]
        assert [(s["street_line_1"], s["region"], s["reason"]) for s in skipped] == [
            ("10 Downing St", "London", "unrecognised_region")
        ]
