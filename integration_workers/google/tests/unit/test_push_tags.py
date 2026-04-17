#!/usr/bin/env python3
"""
Tests for local → Google tag push logic.

TDD: Tests written first before implementation.
Covers tag loading, tag→membership transformation, group pre-creation,
and push payload verification.
"""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/core_shared")


class TestLoadTagNamesForContact:
    """Test loading tag names assigned to a contact for push."""

    @pytest.fixture
    def mock_session(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_loads_tag_names_for_contact(self, mock_session):
        """Test loading tag names returns correct names."""
        from worker import _load_tag_names_for_contact

        mock_result = MagicMock()
        row1 = MagicMock()
        row1.name = "Friends"
        row2 = MagicMock()
        row2.name = "Work"
        mock_result.fetchall.return_value = [row1, row2]
        mock_session.execute.return_value = mock_result

        tag_names = await _load_tag_names_for_contact(mock_session, contact_id=42)

        assert tag_names == ["Friends", "Work"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_tags(self, mock_session):
        """Test returns empty list when contact has no tags."""
        from worker import _load_tag_names_for_contact

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        tag_names = await _load_tag_names_for_contact(mock_session, contact_id=42)

        assert tag_names == []


class TestLoadTagNamesForContactsBatch:
    """Unit tests for batch tag loading function."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_loads_tags_for_multiple_contacts(self, mock_session):
        """Test batch loading returns tags grouped by contact ID."""
        from worker import _load_tag_names_for_contacts_batch

        row1 = MagicMock()
        row1.contact_id = 1
        row1.name = "Friends"
        row2 = MagicMock()
        row2.contact_id = 1
        row2.name = "Work"
        row3 = MagicMock()
        row3.contact_id = 2
        row3.name = "Family"

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row1, row2, row3]
        mock_session.execute.return_value = mock_result

        result = await _load_tag_names_for_contacts_batch(mock_session, [1, 2, 3])

        assert result[1] == ["Friends", "Work"]
        assert result[2] == ["Family"]
        assert result[3] == []  # No tags for contact 3

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_no_contacts(self, mock_session):
        """Test batch loading with empty input returns empty dict."""
        from worker import _load_tag_names_for_contacts_batch

        result = await _load_tag_names_for_contacts_batch(mock_session, [])

        assert result == {}
        mock_session.execute.assert_not_called()


class TestLoadFullContactIncludesTags:
    """Test that _load_full_contact includes tag names."""

    @pytest.fixture
    def mock_session(self):
        """Mock database session with multiple query results."""
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_load_full_contact_includes_tags(self, mock_session):
        """Test that _load_full_contact returns tags in its result."""
        from unittest.mock import patch

        from worker import _load_full_contact

        # Mock each database query in order: methods, addresses, notes, important_dates
        methods_result = MagicMock()
        methods_result.fetchall.return_value = []
        addresses_result = MagicMock()
        addresses_result.fetchall.return_value = []
        notes_result = MagicMock()
        notes_result.fetchall.return_value = []
        dates_result = MagicMock()
        dates_result.fetchall.return_value = []

        mock_session.execute.side_effect = [
            methods_result,
            addresses_result,
            notes_result,
            dates_result,
        ]

        with patch(
            "worker._load_tag_names_for_contact",
            new_callable=AsyncMock,
            return_value=["Friends", "Work"],
        ):
            result = await _load_full_contact(mock_session, contact_id=42)

        assert "tags" in result
        assert result["tags"] == ["Friends", "Work"]


class TestTransformTagsToMemberships:
    """Test transformation of local tag names to Google memberships format."""

    def test_transforms_tags_to_memberships(self):
        """Test basic tag→membership transformation."""
        from worker import _transform_tags_to_memberships

        group_name_to_resource = {
            "Friends": "contactGroups/abc123",
            "Work": "contactGroups/def456",
        }

        result = _transform_tags_to_memberships(
            tag_names=["Friends", "Work"],
            group_name_to_resource=group_name_to_resource,
        )

        assert len(result) == 2
        assert result[0] == {
            "contactGroupMembership": {
                "contactGroupResourceName": "contactGroups/abc123"
            }
        }
        assert result[1] == {
            "contactGroupMembership": {
                "contactGroupResourceName": "contactGroups/def456"
            }
        }

    def test_skips_tags_without_google_group(self):
        """Test that tags without a corresponding Google group are skipped."""
        from worker import _transform_tags_to_memberships

        group_name_to_resource = {
            "Friends": "contactGroups/abc123",
            # "LocalOnly" is not in the mapping
        }

        result = _transform_tags_to_memberships(
            tag_names=["Friends", "LocalOnly"],
            group_name_to_resource=group_name_to_resource,
        )

        assert len(result) == 1
        assert (
            result[0]["contactGroupMembership"]["contactGroupResourceName"]
            == "contactGroups/abc123"
        )

    def test_empty_tags_returns_empty_list(self):
        """Test that empty tag list produces empty memberships."""
        from worker import _transform_tags_to_memberships

        result = _transform_tags_to_memberships(
            tag_names=[],
            group_name_to_resource={"Friends": "contactGroups/abc123"},
        )

        assert result == []

    def test_empty_group_mapping_returns_empty_list(self):
        """Test that empty group mapping produces empty memberships."""
        from worker import _transform_tags_to_memberships

        result = _transform_tags_to_memberships(
            tag_names=["Friends"],
            group_name_to_resource={},
        )

        assert result == []


class TestTransformContactToGooglePersonWithTags:
    """Test that _transform_contact_to_google_person includes memberships."""

    def test_includes_memberships_from_tags(self):
        """Test person payload includes memberships when tags are present."""
        from worker import _transform_contact_to_google_person

        contact = {
            "first_name": "John",
            "last_name": "Doe",
            "methods": [],
            "addresses": [],
            "notes": [],
            "tags": ["Friends", "Work"],
            "group_name_to_resource": {
                "Friends": "contactGroups/abc123",
                "Work": "contactGroups/def456",
            },
        }

        result = _transform_contact_to_google_person(contact)

        assert "memberships" in result
        assert len(result["memberships"]) == 2

    def test_empty_memberships_when_no_tags_but_group_mapping_present(self):
        """Test person payload has empty memberships when tags are empty
        but group_name_to_resource is provided — ensures Google clears
        existing memberships via updatePersonFields mask."""
        from worker import _transform_contact_to_google_person

        contact = {
            "first_name": "John",
            "last_name": "Doe",
            "methods": [],
            "addresses": [],
            "notes": [],
            "tags": [],
            "group_name_to_resource": {},
        }

        result = _transform_contact_to_google_person(contact)

        assert "memberships" in result
        assert result["memberships"] == []

    def test_no_memberships_when_tags_key_missing(self):
        """Test person payload has no memberships when tags key is absent."""
        from worker import _transform_contact_to_google_person

        contact = {
            "first_name": "John",
            "last_name": "Doe",
            "methods": [],
            "addresses": [],
            "notes": [],
        }

        result = _transform_contact_to_google_person(contact)

        assert "memberships" not in result


class TestEnsureGoogleGroupsExist:
    """Test pre-creation of Google groups for local tags."""

    @pytest.mark.asyncio
    async def test_creates_missing_groups(self):
        """Test that groups are created for tags not yet in Google."""
        from worker import _ensure_google_groups_exist

        mock_client = AsyncMock()
        mock_client.create_contact_group.return_value = {
            "resourceName": "contactGroups/new123",
            "name": "NewTag",
        }

        existing_groups = {"ExistingTag": "contactGroups/existing456"}

        result = await _ensure_google_groups_exist(
            client=mock_client,
            tag_names=["ExistingTag", "NewTag"],
            existing_groups=existing_groups,
        )

        # Should contain both existing and newly created
        assert result["ExistingTag"] == "contactGroups/existing456"
        assert result["NewTag"] == "contactGroups/new123"

        # Should only call create for the missing group
        mock_client.create_contact_group.assert_called_once_with("NewTag")

    @pytest.mark.asyncio
    async def test_no_api_calls_when_all_groups_exist(self):
        """Test no API calls made when all groups already exist."""
        from worker import _ensure_google_groups_exist

        mock_client = AsyncMock()

        existing_groups = {
            "Friends": "contactGroups/abc123",
            "Work": "contactGroups/def456",
        }

        result = await _ensure_google_groups_exist(
            client=mock_client,
            tag_names=["Friends", "Work"],
            existing_groups=existing_groups,
        )

        assert result == existing_groups
        mock_client.create_contact_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_group_creation_error_gracefully(self):
        """Test that group creation errors don't fail the entire push."""
        from worker import _ensure_google_groups_exist

        mock_client = AsyncMock()
        mock_client.create_contact_group.side_effect = Exception("API error")

        existing_groups = {"ExistingTag": "contactGroups/existing456"}

        result = await _ensure_google_groups_exist(
            client=mock_client,
            tag_names=["ExistingTag", "FailingTag"],
            existing_groups=existing_groups,
        )

        # Should still contain existing groups
        assert result["ExistingTag"] == "contactGroups/existing456"
        # Failing group should not be in the mapping
        assert "FailingTag" not in result

    @pytest.mark.asyncio
    async def test_empty_tag_names(self):
        """Test with no tag names to process."""
        from worker import _ensure_google_groups_exist

        mock_client = AsyncMock()

        result = await _ensure_google_groups_exist(
            client=mock_client,
            tag_names=[],
            existing_groups={},
        )

        assert result == {}
        mock_client.create_contact_group.assert_not_called()


class TestBuildReverseGroupMapping:
    """Test building name→resource_name mapping for push direction."""

    def test_builds_reverse_mapping(self):
        """Test reversing resource_name→name to name→resource_name."""
        from worker import _build_reverse_group_mapping

        forward_mapping = {
            "contactGroups/abc123": "Friends",
            "contactGroups/def456": "Work",
        }

        result = _build_reverse_group_mapping(forward_mapping)

        assert result == {
            "Friends": "contactGroups/abc123",
            "Work": "contactGroups/def456",
        }

    def test_empty_mapping(self):
        """Test reversing an empty mapping."""
        from worker import _build_reverse_group_mapping

        result = _build_reverse_group_mapping({})

        assert result == {}


class TestGoogleAPIClientGroupManagement:
    """Test cases for Google API client group management methods."""

    @pytest.fixture
    def mock_auth_service(self):
        """Mock Google authentication service."""
        mock_service = AsyncMock()
        mock_service.get_access_token.return_value = "mock_access_token"
        return mock_service

    @pytest.fixture
    def mock_google_service(self):
        """Mock Google People API service."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_create_contact_group_success(
        self, mock_auth_service, mock_google_service
    ):
        """Test successful creation of a Google contact group."""
        from unittest.mock import patch

        from google_client import GoogleAPIClient

        mock_google_service.contactGroups().create().execute.return_value = {
            "resourceName": "contactGroups/new123",
            "name": "MyNewGroup",
            "formattedName": "MyNewGroup",
            "groupType": "USER_CONTACT_GROUP",
        }

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            mock_google_service.contactGroups().create.reset_mock()

            result = await client.create_contact_group("MyNewGroup")

            assert result["resourceName"] == "contactGroups/new123"
            assert result["name"] == "MyNewGroup"

            mock_google_service.contactGroups().create.assert_called_once_with(
                body={"contactGroup": {"name": "MyNewGroup"}}
            )


class TestPushContactWithTagsEndToEnd:
    """End-to-end unit test for pushing a contact with tags to Google."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def mock_google_client(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_push_contact_includes_memberships_in_payload(
        self, mock_session, mock_google_client
    ):
        """Test that pushing a contact with tags includes memberships in the API call."""
        from unittest.mock import patch

        from worker import push_contacts_to_google

        local_contacts = [
            {
                "id": 1,
                "first_name": "Alice",
                "last_name": "Test",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        mock_google_client.create_contact.return_value = {
            "resourceName": "people/c111",
            "etag": "etag_new",
        }

        with (
            patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load,
            patch("worker._upsert_sync_metadata", new_callable=AsyncMock),
            patch(
                "worker._load_tag_names_for_contact",
                new_callable=AsyncMock,
                return_value=["Friends"],
            ),
        ):
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
                "tags": ["Friends"],
            }

            group_name_to_resource = {"Friends": "contactGroups/abc123"}

            result = await push_contacts_to_google(
                session=mock_session,
                client=mock_google_client,
                contacts=local_contacts,
                google_account_email="test@example.com",
                group_name_to_resource=group_name_to_resource,
            )

            assert result["pushed_count"] == 1
            assert result["created_count"] == 1

            # Verify the create_contact call included memberships
            call_args = mock_google_client.create_contact.call_args
            person_data = (
                call_args[0][0]
                if call_args[0]
                else call_args[1].get(
                    "contact_data", call_args[1].get("person_data", {})
                )
            )

            assert "memberships" in person_data
            assert len(person_data["memberships"]) == 1
            assert (
                person_data["memberships"][0]["contactGroupMembership"][
                    "contactGroupResourceName"
                ]
                == "contactGroups/abc123"
            )
