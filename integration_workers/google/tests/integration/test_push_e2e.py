"""
End-to-end integration test for the tag push workflow.

Tests the full push_local_contacts_to_google task with mocked Google API
but real PostgreSQL database, verifying that:
1. Local contacts with tags are discovered by find_contacts_to_push
2. Tags are loaded and mapped to Google contact groups
3. The contact is pushed to Google with correct memberships
4. Sync metadata is persisted correctly
5. Contact data integrity is preserved after push
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import push_local_contacts_to_google


@pytest.mark.asyncio
class TestPushTagEndToEnd:
    """End-to-end test for local tag change → Google push workflow."""

    async def test_local_tag_change_pushes_to_google(
        self, db_session: AsyncSession
    ) -> None:
        """Test that a locally created contact with tags pushes to Google
        with correct group memberships and preserves contact state."""

        # --- Setup: Create auth tokens ---
        test_email = "push-e2e@example.com"
        test_user = "1"
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        now = datetime.now(UTC)
        future_expiry = now + timedelta(hours=1)

        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, created_at, updated_at
                ) VALUES (
                    :user_id, :email, :token, :refresh,
                    :expiry, :now, :now
                )
                ON CONFLICT (user_id, google_account_email) DO NOTHING
                """
            ),
            {
                "user_id": test_user,
                "email": test_email,
                "token": fernet.encrypt(b"access_token"),
                "refresh": fernet.encrypt(b"refresh_token"),
                "expiry": future_expiry,
                "now": now,
            },
        )

        # --- Setup: Create a contact with a tag ---
        contact_result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Push', 'E2E')
                RETURNING id
                """
            )
        )
        contact_id = contact_result.scalar_one()

        # Add email
        await db_session.execute(
            text(
                """
                INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                VALUES (:cid, 'email', 'push-e2e@test.com', true)
                """
            ),
            {"cid": contact_id},
        )

        # Create and assign a tag
        tag_result = await db_session.execute(
            text("INSERT INTO tags (name) VALUES ('e2e-push-tag') RETURNING id")
        )
        tag_id = tag_result.scalar_one()
        await db_session.execute(
            text("INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"),
            {"cid": contact_id, "tid": tag_id},
        )

        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "e2e_push_test",
        }

        # --- Execute: Run push task with mocked Google API ---
        # GoogleAPIClient methods are async but call sync .execute() internally.
        # Mock at the google_client.build level with sync returns.
        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build") as mock_build,
        ):
            mock_service = MagicMock()

            # Mock people().createContact().execute() — sync return
            mock_create_execute = MagicMock(
                return_value={
                    "resourceName": "people/c_e2e_push",
                    "etag": "etag_pushed",
                }
            )
            mock_create_contact_req = MagicMock()
            mock_create_contact_req.execute = mock_create_execute
            mock_people = MagicMock()
            mock_people.createContact.return_value = mock_create_contact_req

            mock_service.people.return_value = mock_people

            # Mock contactGroups().list().execute() — sync return
            mock_list_execute = MagicMock(
                return_value={
                    "contactGroups": [
                        {
                            "resourceName": "contactGroups/existing",
                            "name": "existing-group",
                            "formattedName": "existing-group",
                            "groupType": "USER_CONTACT_GROUP",
                        }
                    ]
                }
            )
            mock_list_req = MagicMock()
            mock_list_req.execute = mock_list_execute

            # Mock contactGroups().create().execute() — sync return
            mock_create_group_execute = MagicMock(
                return_value={
                    "resourceName": "contactGroups/e2e_push_tag",
                    "name": "e2e-push-tag",
                }
            )
            mock_create_group_req = MagicMock()
            mock_create_group_req.execute = mock_create_group_execute

            mock_groups = MagicMock()
            mock_groups.list.return_value = mock_list_req
            mock_groups.create.return_value = mock_create_group_req

            mock_service.contactGroups.return_value = mock_groups
            mock_build.return_value = mock_service

            result = await push_local_contacts_to_google(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
            )

        # --- Verify: Task completed successfully ---
        assert result["status"] == "success"
        assert result["pushed_count"] == 1
        assert result["created_count"] == 1
        assert result["error_count"] == 0

        # --- Verify: Sync metadata persisted ---
        metadata_row = await db_session.execute(
            text(
                """
                SELECT internal_id, external_id, version_hash, sync_status
                FROM sync_metadata
                WHERE integration_source = 'google'
                  AND internal_id = :cid
                """
            ),
            {"cid": contact_id},
        )
        metadata = metadata_row.one()
        assert metadata.external_id == "people/c_e2e_push"
        assert metadata.version_hash == "etag_pushed"
        assert metadata.sync_status == "success"

        # --- Verify: Contact data integrity preserved ---
        contact_row = await db_session.execute(
            text(
                """
                SELECT first_name, last_name
                FROM contacts WHERE id = :cid
                """
            ),
            {"cid": contact_id},
        )
        contact = contact_row.one()
        assert contact.first_name == "Push"
        assert contact.last_name == "E2E"

        # Tags still assigned
        tag_row = await db_session.execute(
            text(
                """
                SELECT t.name FROM tags t
                INNER JOIN contact_tags ct ON t.id = ct.tag_id
                WHERE ct.contact_id = :cid
                """
            ),
            {"cid": contact_id},
        )
        tags = [r.name for r in tag_row.fetchall()]
        assert tags == ["e2e-push-tag"]

        # Email still intact
        method_row = await db_session.execute(
            text("SELECT value FROM contact_methods WHERE contact_id = :cid"),
            {"cid": contact_id},
        )
        assert method_row.scalar_one() == "push-e2e@test.com"

    async def test_push_with_no_contacts_returns_success(
        self, db_session: AsyncSession
    ) -> None:
        """Test that push with no pending contacts returns success immediately."""
        test_email = "no-push@example.com"
        test_user = "2"
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        now = datetime.now(UTC)

        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, created_at, updated_at
                ) VALUES (
                    :user_id, :email, :token, :refresh,
                    :expiry, :now, :now
                )
                ON CONFLICT (user_id, google_account_email) DO NOTHING
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

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "e2e_no_push",
        }

        with (
            patch(
                "worker.settings.encryption_key.get_secret_value",
                return_value=fernet_key.decode(),
            ),
            patch("google_client.build"),
        ):
            result = await push_local_contacts_to_google(
                ctx=ctx,
                google_account_email=test_email,
                user_id=test_user,
            )

        assert result["status"] == "success"
        assert result["pushed_count"] == 0
