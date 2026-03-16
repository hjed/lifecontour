"""
Integration tests for tag push and conflict scenarios with real database.

Tests push_contacts_to_google with mocked Google API client but real
PostgreSQL database to verify that sync metadata is correctly persisted
and that conflict handling (409 ETag mismatch) works end-to-end.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import push_contacts_to_google


@pytest_asyncio.fixture
async def push_contact_data(db_session: AsyncSession) -> dict:  # type: ignore[type-arg]
    """Create a contact with tags for push testing.

    Returns:
        Dict with contact IDs and tag info for assertions.
    """
    # Create a contact
    result = await db_session.execute(
        text(
            """
            INSERT INTO contacts (first_name, last_name)
            VALUES ('Push', 'Test')
            RETURNING id
            """
        )
    )
    contact_id = result.scalar_one()

    # Add an email method
    await db_session.execute(
        text(
            """
            INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
            VALUES (:cid, 'email', 'push@test.com', true)
            """
        ),
        {"cid": contact_id},
    )

    # Create and assign a tag
    tag_result = await db_session.execute(
        text("INSERT INTO tags (name) VALUES ('push-tag') RETURNING id")
    )
    tag_id = tag_result.scalar_one()
    await db_session.execute(
        text("INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"),
        {"cid": contact_id, "tid": tag_id},
    )
    await db_session.flush()

    return {"contact_id": contact_id, "tag_id": tag_id}


def _make_mock_google_client() -> MagicMock:
    """Create a mock GoogleAPIClient with default responses."""
    client = AsyncMock()
    client.create_contact.return_value = {
        "resourceName": "people/c999",
        "etag": "etag_created",
    }
    client.update_contact.return_value = {
        "resourceName": "people/c999",
        "etag": "etag_updated",
    }
    return client


@pytest.mark.asyncio
class TestPushContactsWithRealDB:
    """Integration tests for push_contacts_to_google with real database."""

    async def test_create_push_writes_sync_metadata(
        self, db_session: AsyncSession, push_contact_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Test that pushing a new contact writes sync_metadata to the DB."""
        contact_id = push_contact_data["contact_id"]
        mock_client = _make_mock_google_client()

        contacts = [
            {
                "id": contact_id,
                "first_name": "Push",
                "last_name": "Test",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        group_mapping = {"push-tag": "contactGroups/pushGroup"}

        result = await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
            group_name_to_resource=group_mapping,
        )

        assert result["pushed_count"] == 1
        assert result["created_count"] == 1
        assert result["error_count"] == 0

        # Verify sync_metadata was written to real DB
        metadata = await db_session.execute(
            text(
                """
                SELECT internal_id, external_id, version_hash, sync_status
                FROM sync_metadata
                WHERE integration_source = 'google'
                  AND external_id = 'people/c999'
                """
            )
        )
        row = metadata.one()
        assert row.internal_id == contact_id
        assert row.external_id == "people/c999"
        assert row.version_hash == "etag_created"
        assert row.sync_status == "success"

    async def test_update_push_updates_sync_metadata(
        self, db_session: AsyncSession, push_contact_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Test that updating a contact updates sync_metadata in the DB."""
        contact_id = push_contact_data["contact_id"]

        # Pre-create sync metadata (simulating a previously synced contact)
        await db_session.execute(
            text(
                """
                INSERT INTO sync_metadata
                    (internal_id, integration_source, external_id,
                     version_hash, sync_status, last_synced_at,
                     created_at, updated_at)
                VALUES
                    (:cid, 'google', 'people/c999',
                     'etag_old', 'success', NOW(), NOW(), NOW())
                """
            ),
            {"cid": contact_id},
        )
        await db_session.flush()

        mock_client = _make_mock_google_client()
        contacts = [
            {
                "id": contact_id,
                "first_name": "Push",
                "last_name": "Test",
                "sync_action": "update",
                "external_id": "people/c999",
                "version_hash": "etag_old",
            }
        ]

        result = await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
            group_name_to_resource={"push-tag": "contactGroups/pushGroup"},
        )

        assert result["pushed_count"] == 1
        assert result["updated_count"] == 1

        # Verify sync_metadata was updated with new ETag
        metadata = await db_session.execute(
            text(
                """
                SELECT version_hash, sync_status
                FROM sync_metadata
                WHERE integration_source = 'google'
                  AND external_id = 'people/c999'
                """
            )
        )
        row = metadata.one()
        assert row.version_hash == "etag_updated"
        assert row.sync_status == "success"

    async def test_push_includes_memberships_in_payload(
        self, db_session: AsyncSession, push_contact_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Test that push includes group memberships from tag mapping."""
        contact_id = push_contact_data["contact_id"]
        mock_client = _make_mock_google_client()

        contacts = [
            {
                "id": contact_id,
                "first_name": "Push",
                "last_name": "Test",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        group_mapping = {"push-tag": "contactGroups/pushGroup"}

        await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
            group_name_to_resource=group_mapping,
        )

        # Verify the Google API was called with memberships
        call_args = mock_client.create_contact.call_args
        person_data = call_args[0][0]
        assert "memberships" in person_data
        assert len(person_data["memberships"]) == 1
        assert (
            person_data["memberships"][0]["contactGroupMembership"][
                "contactGroupResourceName"
            ]
            == "contactGroups/pushGroup"
        )

    async def test_push_empty_tags_sends_empty_memberships(
        self, db_session: AsyncSession
    ) -> None:
        """Test that a contact with no tags still sends empty memberships
        when group_name_to_resource is provided (to clear Google groups)."""
        # Create a contact with NO tags
        result = await db_session.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES ('NoTag', 'Push')
                RETURNING id
                """
            )
        )
        contact_id = result.scalar_one()
        await db_session.flush()

        mock_client = _make_mock_google_client()
        contacts = [
            {
                "id": contact_id,
                "first_name": "NoTag",
                "last_name": "Push",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        # Empty mapping = tag push active, but no tags to map
        await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
            group_name_to_resource={},
        )

        call_args = mock_client.create_contact.call_args
        person_data = call_args[0][0]
        # Should include memberships key with empty list
        assert "memberships" in person_data
        assert person_data["memberships"] == []


@pytest.mark.asyncio
class TestPushConflictHandling:
    """Integration tests for conflict handling during push."""

    async def test_412_conflict_increments_conflict_count(
        self, db_session: AsyncSession, push_contact_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Test that a 412 Precondition Failed from Google is recorded as conflict."""
        from unittest.mock import PropertyMock

        contact_id = push_contact_data["contact_id"]
        mock_client = _make_mock_google_client()

        # Simulate 412 Precondition Failed (ETag mismatch)
        mock_response = MagicMock()
        type(mock_response).status = PropertyMock(return_value=412)
        mock_response.reason = "Precondition Failed"

        from googleapiclient.errors import HttpError

        mock_client.create_contact.side_effect = HttpError(
            resp=mock_response,
            content=b"Precondition Failed",
        )

        contacts = [
            {
                "id": contact_id,
                "first_name": "Push",
                "last_name": "Test",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        result = await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
        )

        assert result["pushed_count"] == 0
        assert result["conflict_count"] == 1
        assert result["error_count"] == 1

    async def test_500_error_increments_error_count(
        self, db_session: AsyncSession, push_contact_data: dict  # type: ignore[type-arg]
    ) -> None:
        """Test that a 500 error from Google is recorded in metrics."""
        from unittest.mock import PropertyMock

        contact_id = push_contact_data["contact_id"]
        mock_client = _make_mock_google_client()

        # Simulate 500 Server Error
        mock_response = MagicMock()
        type(mock_response).status = PropertyMock(return_value=500)
        mock_response.reason = "Internal Server Error"

        from googleapiclient.errors import HttpError

        mock_client.create_contact.side_effect = HttpError(
            resp=mock_response,
            content=b"Server error",
        )

        contacts = [
            {
                "id": contact_id,
                "first_name": "Push",
                "last_name": "Test",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        result = await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=contacts,
            google_account_email="test@example.com",
        )

        assert result["pushed_count"] == 0
        assert result["error_count"] == 1
        # 500 is not a conflict
        assert result["conflict_count"] == 0
