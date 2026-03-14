"""Integration tests for reserved group filtering and name translation."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import sync_google_contacts


@pytest.mark.asyncio
class TestReservedGroupsIntegration:
    """Integration test for reserved group filtering and translation in full sync flow."""

    async def test_full_sync_with_groups_and_starred(
        self, db_session: AsyncSession
    ) -> None:
        """Test sync handles 'starred', reserved groups, and translates other group IDs."""
        now = datetime.now(UTC)
        future_expiry = now + timedelta(hours=1)
        test_email = "groups_sync_test@example.com"
        test_user = "3"

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
                    (:user_id, :email, :token, :refresh,
                     :expiry, :now, :now)
                ON CONFLICT (user_id, google_account_email) DO UPDATE SET
                    encrypted_access_token = EXCLUDED.encrypted_access_token,
                    encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at
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
        async def mock_session_factory() -> Any:
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": None,
            "job_id": "test_job_groups_123",
        }

        # Mock API Responses
        def mock_groups_list_execute() -> dict[str, Any]:
            return {
                "contactGroups": [
                    {
                        "resourceName": "contactGroups/myContacts",
                        "name": "System Group: My Contacts",
                        "formattedName": "My Contacts",
                    },
                    {
                        "resourceName": "contactGroups/family",
                        "name": "Family",
                        "formattedName": "Family",
                    },
                ]
            }

        def mock_connections_list_execute() -> dict[str, Any]:
            return {
                "connections": [
                    {
                        "resourceName": "people/c1_starred_family_mycontacts",
                        "etag": "etag_1",
                        "names": [{"givenName": "Alice", "familyName": "Smith"}],
                        "memberships": [
                            {
                                "contactGroupMembership": {
                                    "contactGroupId": "starred",
                                    "contactGroupResourceName": "contactGroups/starred",
                                }
                            },
                            {
                                "contactGroupMembership": {
                                    "contactGroupId": "myContacts",
                                    "contactGroupResourceName": "contactGroups/myContacts",
                                }
                            },
                            {
                                "contactGroupMembership": {
                                    "contactGroupId": "family",
                                    "contactGroupResourceName": "contactGroups/family",
                                }
                            },
                        ],
                    }
                ]
            }

        # Setup Mocks
        mock_contact_groups_list = MagicMock()
        mock_contact_groups_list.execute.side_effect = mock_groups_list_execute

        mock_contact_groups = MagicMock()
        mock_contact_groups.list.return_value = mock_contact_groups_list

        mock_connections_list = MagicMock()
        mock_connections_list.execute.side_effect = mock_connections_list_execute

        mock_connections = MagicMock()
        mock_connections.list.return_value = mock_connections_list

        mock_people = MagicMock()
        mock_people.connections.return_value = mock_connections

        mock_service = MagicMock()
        mock_service.people.return_value = mock_people
        mock_service.contactGroups.return_value = mock_contact_groups

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

            # Check the outbox event payload to ensure mapping worked properly
            result_outbox = await db_session.execute(
                text(
                    "SELECT event_data FROM outbox_events WHERE (event_data::jsonb)->>'external_id' = 'people/c1_starred_family_mycontacts'"
                )
            )
            outbox_event_data = result_outbox.scalar()
            assert outbox_event_data is not None

            if isinstance(outbox_event_data, str):
                import json

                outbox_event_data = json.loads(outbox_event_data)

            contact_data = outbox_event_data.get("contact_data", {})
            assert contact_data.get("is_favourite") is True

            tags = contact_data.get("tags", [])
            tag_names = [t.get("name") for t in tags]

            assert "Family" in tag_names
            assert "System Group: My Contacts" not in tag_names
            assert "My Contacts" not in tag_names
            assert "starred" not in tag_names
            assert len(tags) == 1
