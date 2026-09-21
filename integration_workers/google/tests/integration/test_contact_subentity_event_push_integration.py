"""Integration tests for the contact sub-entity events LOCAL-177 restored.

Adding a tag publishes ``TagAssigned``; adding or removing an email publishes
``ContactMethodAdded``/``ContactMethodDeleted``; the important-date UI publishes
``ImportantDate*``. None of these were routed to the Google worker, so the
changes were read off the stream, acknowledged and dropped, and the next inbound
sync overwrote them.

These tests run the handler against a real database (real ``contacts``,
``contact_methods``, ``tags``, ``contact_tags``, ``sync_metadata`` and
``user_google_auth`` rows) with only the Google API client mocked, so they prove
the whole read-contact → transform → push path — not just the routing.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_contact_event

_REMOTE = "people/c-subentity-1"
_NEW_ETAG = "etag-after-push"


def _session_factory(db_session: AsyncSession) -> Any:
    """Build a session_factory that yields the test's transactional session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return factory


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    return {
        "session_factory": _session_factory(db_session),
        "job_id": "evt-subentity-it",
    }


def _mock_google_client(groups: dict[str, str] | None = None) -> AsyncMock:
    """A Google client whose writes return a fresh resource name and etag.

    ``groups`` maps a contact-group display name to its resource name and seeds
    ``contactGroups.list``; anything the contact needs and is missing is created
    through ``create_contact_group``.
    """
    client = AsyncMock()
    client.update_contact.return_value = {
        "resourceName": _REMOTE,
        "etag": _NEW_ETAG,
    }
    client.create_contact.return_value = {
        "resourceName": _REMOTE,
        "etag": _NEW_ETAG,
    }
    client.list_contact_groups.return_value = {
        "contactGroups": [
            {"resourceName": resource, "name": name, "formattedName": name}
            for name, resource in (groups or {}).items()
        ]
    }
    client.create_contact_group.return_value = {
        "resourceName": "contactGroups/created-for-tag"
    }
    return client


def _pushed_membership_resources(client: AsyncMock) -> list[str]:
    """The contact-group resource names in the person the worker pushed."""
    pushed = client.update_contact.call_args[1]["contact_data"]
    return [
        entry["contactGroupMembership"]["contactGroupResourceName"]
        for entry in pushed.get("memberships", [])
    ]


@pytest_asyncio.fixture
async def synced_contact(db_session: AsyncSession) -> dict[str, int]:
    """A Google-linked contact with one email and one tag.

    Returns the contact and tag ids so tests can address them.
    """
    await db_session.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES ('1', 'subentity-it@example.com', :token, :refresh,
                      NOW(), NOW(), NOW())
            ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
        ),
        {"token": b"x", "refresh": b"y"},
    )

    result = await db_session.execute(
        text(
            """
            INSERT INTO contacts (first_name, last_name)
            VALUES ('Sub', 'Entity')
            RETURNING id
            """
        )
    )
    contact_id = int(result.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
            VALUES (:cid, 'email', 'renamed@example.com', true)
            """
        ),
        {"cid": contact_id},
    )

    result = await db_session.execute(
        text("INSERT INTO tags (name) VALUES ('Colleagues') RETURNING id")
    )
    tag_id = int(result.scalar_one())
    await db_session.execute(
        text("INSERT INTO contact_tags (contact_id, tag_id) VALUES (:cid, :tid)"),
        {"cid": contact_id, "tid": tag_id},
    )

    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 internal_entity_type, external_entity_type,
                 created_at, updated_at)
            VALUES (:cid, 'google', :ext, 'etag-before', 'success', NOW(),
                    'contact', 'person', NOW(), NOW())
            """
        ),
        {"cid": contact_id, "ext": _REMOTE},
    )
    await db_session.flush()

    return {"contact_id": contact_id, "tag_id": tag_id}


async def _stored_version_hash(db_session: AsyncSession, contact_id: int) -> str:
    result = await db_session.execute(
        text(
            """
            SELECT version_hash FROM sync_metadata
            WHERE integration_source = 'google' AND internal_id = :cid
            """
        ),
        {"cid": contact_id},
    )
    return str(result.scalar_one())


@pytest.mark.asyncio
class TestSubEntityEventsReachGoogle:
    """Each previously dropped event pushes the contact's current state."""

    @pytest.mark.parametrize(
        "event_type",
        [
            "TagAssigned",
            "TagRemoved",
            "ContactMethodAdded",
            "ContactMethodDeleted",
            "ContactAddressAdded",
            "ContactAddressDeleted",
            "ContactNoteAdded",
            "ImportantDateAdded",
            "ImportantDateUpdated",
            "ImportantDateDeleted",
        ],
    )
    async def test_event_pushes_contact_to_google(
        self,
        db_session: AsyncSession,
        synced_contact: dict[str, int],
        event_type: str,
    ) -> None:
        """The handler updates the linked Google person for every routed event."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type=event_type,
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        assert result["status"] == "success"
        mock_client.update_contact.assert_called_once()
        assert mock_client.update_contact.call_args[1]["resource_name"] == _REMOTE

    async def test_contact_method_event_pushes_the_current_email(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """The pushed person carries the email as it now stands in the database.

        This is the reported symptom: an email change that never reached Google.
        """
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMethodAdded",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        pushed = mock_client.update_contact.call_args[1]["contact_data"]
        assert [entry["value"] for entry in pushed["emailAddresses"]] == [
            "renamed@example.com"
        ]

    async def test_push_advances_the_stored_etag(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """sync_metadata records Google's new etag, so the next pull is a no-op.

        Without this the inbound sync would see a changed etag and re-apply
        Google's copy over the local edit.
        """
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagAssigned",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        assert await _stored_version_hash(db_session, contact_id) == _NEW_ETAG

    async def test_stale_etag_is_sent_for_optimistic_concurrency(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """The stored etag is passed to the update so Google can detect conflicts."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMethodDeleted",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        assert mock_client.update_contact.call_args[1]["etag"] == "etag-before"


@pytest.mark.asyncio
class TestInboundEchoIsNotPushedBack:
    """An event the inbound sync caused must not be written back to Google."""

    async def test_inbound_sourced_event_makes_no_google_call(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """Google's own data is not pushed back to Google."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagAssigned",
                event_data={"contact_id": contact_id, "source": "google_contacts"},
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "inbound_echo"
        mock_client.update_contact.assert_not_called()
        # The stored etag is untouched, so the next pull still reconciles.
        assert await _stored_version_hash(db_session, contact_id) == "etag-before"


@pytest.mark.asyncio
class TestTagMembershipsReachGoogle:
    """LOCAL-177: the event push path never sent contact-group memberships.

    ``_push_contact_to_google_for_event`` built no group mapping, so
    ``_transform_contact_to_google_person`` omitted ``memberships`` and a tag
    change could not reach Google even once its event was routed.
    """

    async def test_existing_group_is_pushed_as_a_membership(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """The contact's tag is sent as a membership of its Google group."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client(
            groups={"Colleagues": "contactGroups/colleagues1"}
        )

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagAssigned",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        assert _pushed_membership_resources(mock_client) == [
            "contactGroups/myContacts",
            "contactGroups/colleagues1",
        ]
        mock_client.create_contact_group.assert_not_called()

    async def test_missing_group_is_created_then_pushed(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """A tag with no Google group yet gets one before the contact is pushed."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client(groups={})

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagAssigned",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        mock_client.create_contact_group.assert_called_once_with("Colleagues")
        assert _pushed_membership_resources(mock_client) == [
            "contactGroups/myContacts",
            "contactGroups/created-for-tag",
        ]

    async def test_removing_the_last_tag_clears_groups_but_keeps_my_contacts(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """A contact with no tags left sends only the reserved memberships.

        The mask replaces the list, so this is how a removed tag clears its
        Google group — while ``myContacts`` must survive, or the contact drops
        out of the user's contacts entirely.
        """
        contact_id = synced_contact["contact_id"]
        await db_session.execute(
            text("DELETE FROM contact_tags WHERE contact_id = :cid"),
            {"cid": contact_id},
        )
        await db_session.flush()

        mock_client = _mock_google_client(
            groups={"Colleagues": "contactGroups/colleagues1"}
        )

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagRemoved",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        assert _pushed_membership_resources(mock_client) == ["contactGroups/myContacts"]

    async def test_memberships_are_in_the_update_field_mask(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """Google only applies fields named in updatePersonFields.

        The mask is derived from the payload's keys, so this asserts the key is
        present rather than re-deriving the mask.
        """
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client(
            groups={"Colleagues": "contactGroups/colleagues1"}
        )

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="TagAssigned",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        pushed = mock_client.update_contact.call_args[1]["contact_data"]
        assert "memberships" in pushed


@pytest.mark.asyncio
class TestDeletingTheLastValueClearsGoogle:
    """Augment review of #1548: a deletion must name the field it empties.

    ``updatePersonFields`` is derived from the payload's keys, so a payload that
    omits an emptied list leaves the stale value in Google — and the next pull,
    seeing a changed etag, re-imports what the user deleted.
    """

    async def test_deleting_the_last_email_sends_an_empty_email_list(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """ContactMethodDeleted for the only email clears it remotely."""
        contact_id = synced_contact["contact_id"]
        await db_session.execute(
            text("DELETE FROM contact_methods WHERE contact_id = :cid"),
            {"cid": contact_id},
        )
        await db_session.flush()

        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMethodDeleted",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        pushed = mock_client.update_contact.call_args[1]["contact_data"]
        assert pushed["emailAddresses"] == []
        assert pushed["phoneNumbers"] == []

    async def test_deleting_the_last_address_sends_an_empty_address_list(
        self, db_session: AsyncSession, synced_contact: dict[str, int]
    ) -> None:
        """ContactAddressDeleted for a contact left with no address clears it."""
        contact_id = synced_contact["contact_id"]
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactAddressDeleted",
                event_data={"contact_id": contact_id, "source": "ui"},
            )

        pushed = mock_client.update_contact.call_args[1]["contact_data"]
        assert pushed["addresses"] == []
