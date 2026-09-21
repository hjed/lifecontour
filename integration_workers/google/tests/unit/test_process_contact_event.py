"""Unit tests for process_contact_event worker function.

Tests the event-driven outbound push of contacts to Google when
ContactCreated, ContactUpdated, or ContactDeleted domain events
are received from the Redis Stream.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_ctx(session_factory: Any = None) -> dict[str, Any]:
    """Build an ARQ-compatible context dict."""
    return {
        "session_factory": session_factory or MagicMock(),
        "job_id": "evt-contact-test-001",
    }


def _google_client() -> AsyncMock:
    """A Google client whose contact-group listing succeeds with no groups.

    The push resolves tag groups before writing, and a listing failure now
    raises rather than being swallowed. A bare ``MagicMock`` client cannot be
    awaited, so these dispatch-focused tests need a client that lists cleanly.
    """
    client = AsyncMock()
    client.list_contact_groups.return_value = {"contactGroups": []}
    return client


def _mock_session_factory(
    sync_row: Any = None,
    users: list[Any] | None = None,
    tag_names: list[str] | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory with the queries the handler runs.

    The code executes queries in this order:
      1. the per-contact push lock (advisory, result unused)
      2. sync_metadata lookup (fetchone)
      3. user_google_auth lookup (fetchall)
      4. the contact's tag names (fetchall), skipped for ContactDeleted

    Returns:
        (factory, mock_session) — the factory to pass to _make_ctx and
        the mock session for further assertions.
    """
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # sync_metadata result
    mock_sync_result = MagicMock()
    mock_sync_result.fetchone.return_value = sync_row

    # user_google_auth result
    mock_users_result = MagicMock()
    mock_users_result.fetchall.return_value = users or []

    # tag-name result — rows expose the recursive CTE's `name` column
    mock_tags_result = MagicMock()
    mock_tags_result.fetchall.return_value = [
        MagicMock(name=name) for name in tag_names or []
    ]

    mock_session.execute.side_effect = [
        MagicMock(),  # 1st call: per-contact push lock
        mock_sync_result,  # 2nd call: sync_metadata
        mock_users_result,  # 3rd call: user_google_auth
        mock_tags_result,  # 4th call: contact tag names
    ]

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_factory, mock_session


class TestProcessContactEventRouting:
    """Verify process_contact_event routes to correct logic based on event_type."""

    @pytest.mark.asyncio
    async def test_returns_error_when_contact_id_missing(self) -> None:
        """process_contact_event returns error status when event_data lacks contact_id."""
        from worker import process_contact_event

        result = await process_contact_event(
            ctx=_make_ctx(),
            event_type="ContactUpdated",
            event_data={},  # no contact_id
        )

        assert result["status"] == "error"
        assert "contact_id" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_skips_when_no_google_integrations(self) -> None:
        """When no Google integrations exist, the event is silently skipped."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(sync_row=None, users=[])

        result = await process_contact_event(
            ctx=_make_ctx(mock_factory),
            event_type="ContactUpdated",
            event_data={"contact_id": 42},
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_google_integrations"


class TestProcessContactCreated:
    """Verify ContactCreated triggers outbound push with sync_action='create'."""

    @pytest.mark.asyncio
    async def test_creates_contact_in_google(self) -> None:
        """ContactCreated event pushes a new contact to Google."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,  # no prior sync metadata
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "created"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactCreated",
                event_data={"contact_id": 42, "first_name": "Jane", "last_name": "Doe"},
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args[1]
        assert call_kwargs["contact_id"] == 42
        assert call_kwargs["sync_action"] == "create"


class TestProcessContactUpdated:
    """Verify ContactUpdated triggers outbound push with sync_action='update'."""

    @pytest.mark.asyncio
    async def test_updates_existing_contact_in_google(self) -> None:
        """ContactUpdated event pushes an update when sync metadata exists."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "updated"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactUpdated",
                event_data={
                    "contact_id": 42,
                    "changed_fields": {"nick_name": ("Old", "New")},
                },
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args[1]
        assert call_kwargs["contact_id"] == 42
        assert call_kwargs["sync_action"] == "update"
        assert call_kwargs["external_id"] == "people/c123"
        assert call_kwargs["version_hash"] == "etag-old"

    @pytest.mark.asyncio
    async def test_creates_in_google_when_no_sync_metadata(self) -> None:
        """ContactUpdated creates in Google when no prior sync metadata exists."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "created"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactUpdated",
                event_data={"contact_id": 42, "changed_fields": {}},
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args[1]
        assert call_kwargs["sync_action"] == "create"


class TestProcessContactDeleted:
    """Verify ContactDeleted triggers delete in Google."""

    @pytest.mark.asyncio
    async def test_deletes_contact_from_google(self) -> None:
        """ContactDeleted event deletes the contact from Google."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._delete_contact_from_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "deleted"},
            ) as mock_delete,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactDeleted",
                event_data={"contact_id": 42},
            )

        assert result["status"] == "success"
        mock_delete.assert_called_once()
        call_kwargs = mock_delete.call_args[1]
        assert call_kwargs["external_id"] == "people/c123"

    @pytest.mark.asyncio
    async def test_skips_delete_when_no_sync_metadata(self) -> None:
        """ContactDeleted continues (skips) per-account when no sync metadata exists."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactDeleted",
                event_data={"contact_id": 42},
            )

        # The overall call succeeds; individual account is skipped
        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "skipped"
        assert result["results"][0]["reason"] == "no_sync_metadata"


def _mock_merge_session_factory(
    users: list[Any] | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory for the ContactMerged handler.

    The merge handler does not do a ``contact_id``-keyed sync_metadata lookup
    (the event carries no ``contact_id``); its only direct query is the
    ``user_google_auth`` lookup (``fetchall``), so a single ``execute`` result
    suffices when the per-collision delete helper is patched.
    """
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_users_result = MagicMock()
    mock_users_result.fetchall.return_value = users or []
    mock_session.execute.return_value = mock_users_result

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    return mock_factory, mock_session


_GOOGLE_COLLISION = {
    "external_system": "google",
    "external_entity_type": "person",
    "source_external_id": "people/source123",
    "survivor_external_id": "people/survivor456",
}


class TestProcessContactMerged:
    """Verify ContactMerged deletes the source's remote Google contact.

    ITER13-005 Phase 2: the merge already deleted the source's *local*
    sync_metadata/external_references inline (Phase 1) and surfaced the
    same-service clash on ``external_collisions``. The worker uses
    ``source_external_id`` from that payload to delete the orphaned *remote*
    record; the survivor's Google contact is reconciled by the separate
    ``ContactUpdated`` event, not here.
    """

    @pytest.mark.asyncio
    async def test_deletes_source_remote_for_google_collision(self) -> None:
        """A same-service (google) collision deletes exactly the source remote."""
        from worker import process_contact_event

        mock_factory, _ = _mock_merge_session_factory(
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._delete_contact_from_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "deleted", "external_id": "people/source123"},
            ) as mock_delete,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_GOOGLE_COLLISION],
                },
            )

        assert result["status"] == "success"
        mock_delete.assert_called_once()
        call_kwargs = mock_delete.call_args[1]
        assert call_kwargs["external_id"] == "people/source123"
        assert call_kwargs["contact_id"] == 2

    @pytest.mark.asyncio
    async def test_skips_when_no_google_collision(self) -> None:
        """A different-service (or empty) collision set triggers no Google deletion."""
        from worker import process_contact_event

        immich_collision = {
            "external_system": "immich",
            "external_entity_type": "person",
            "source_external_id": "person-abc",
            "survivor_external_id": "person-def",
        }

        with patch(
            "worker._delete_contact_from_google_for_event",
            new_callable=AsyncMock,
        ) as mock_delete:
            result = await process_contact_event(
                ctx=_make_ctx(),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [immich_collision],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_google_collisions"
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_google_integrations(self) -> None:
        """A google collision with no connected Google accounts performs no remote call."""
        from worker import process_contact_event

        mock_factory, _ = _mock_merge_session_factory(users=[])

        with (
            patch(
                "worker._delete_contact_from_google_for_event",
                new_callable=AsyncMock,
            ) as mock_delete,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_GOOGLE_COLLISION],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_google_integrations"
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_require_contact_id(self) -> None:
        """ContactMerged (no contact_id) must not hit the missing-contact_id error path."""
        from worker import process_contact_event

        result = await process_contact_event(
            ctx=_make_ctx(),
            event_type="ContactMerged",
            event_data={
                "survivor_contact_id": 1,
                "source_contact_id": 2,
                "external_collisions": [],
            },
        )

        # Empty collisions short-circuits to a skip — crucially NOT an error.
        assert result["status"] == "skipped"
        assert result["reason"] == "no_google_collisions"

    @pytest.mark.asyncio
    async def test_deletes_each_google_collision(self) -> None:
        """Multiple google collisions delete one source remote each."""
        from worker import process_contact_event

        second_collision = {
            "external_system": "google",
            "external_entity_type": "person",
            "source_external_id": "people/source789",
            "survivor_external_id": "people/survivor456",
        }

        mock_factory, _ = _mock_merge_session_factory(
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._delete_contact_from_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "deleted"},
            ) as mock_delete,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_GOOGLE_COLLISION, second_collision],
                },
            )

        assert result["status"] == "success"
        assert mock_delete.call_count == 2
        deleted_ids = {c.kwargs["external_id"] for c in mock_delete.call_args_list}
        assert deleted_ids == {"people/source123", "people/source789"}


class TestProcessContactEventErrorHandling:
    """Verify process_contact_event handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_raises_on_push_failure(self) -> None:
        """process_contact_event raises when push fails (for ARQ retry)."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                side_effect=Exception("Google API error"),
            ),
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
            pytest.raises(Exception, match="Google API error"),
        ):
            await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactCreated",
                event_data={"contact_id": 42},
            )


class TestPushContactToGoogleForEvent:
    """Verify the per-account push helper works correctly."""

    @pytest.mark.asyncio
    async def test_push_create_calls_google_create(self) -> None:
        """_push_contact_to_google_for_event creates a contact in Google API."""
        from worker import _push_contact_to_google_for_event

        mock_session = AsyncMock()

        # Mock the base contact query result
        mock_base_row = MagicMock()
        mock_base_row.first_name = "Jane"
        mock_base_row.last_name = "Doe"
        mock_base_row.middle_name = None
        mock_base_row.nick_name = None
        mock_base_row.is_favourite = False
        mock_base_row.company = None
        mock_base_row.job_title = None

        mock_base_result = MagicMock()
        mock_base_result.fetchone.return_value = mock_base_row
        mock_session.execute.return_value = mock_base_result

        mock_client = AsyncMock()
        mock_client.create_contact.return_value = {
            "resourceName": "people/c999",
            "etag": "new-etag",
        }

        with (
            patch(
                "worker._load_full_contact",
                new_callable=AsyncMock,
                return_value={
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                    "important_dates": [],
                },
            ),
            patch(
                "worker._transform_contact_to_google_person",
                return_value={"names": [{"givenName": "Jane", "familyName": "Doe"}]},
            ),
            patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert,
        ):
            result = await _push_contact_to_google_for_event(
                session=mock_session,
                client=mock_client,
                contact_id=42,
                sync_action="create",
                google_account_email="test@gmail.com",
                external_id=None,
                version_hash=None,
            )

        assert result["status"] == "created"
        mock_client.create_contact.assert_called_once()
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_update_calls_google_update(self) -> None:
        """_push_contact_to_google_for_event updates a contact in Google API."""
        from worker import _push_contact_to_google_for_event

        mock_session = AsyncMock()

        # Mock the base contact query result
        mock_base_row = MagicMock()
        mock_base_row.first_name = "Jane"
        mock_base_row.last_name = "Doe"
        mock_base_row.middle_name = None
        mock_base_row.nick_name = "JD"
        mock_base_row.is_favourite = False
        mock_base_row.company = None
        mock_base_row.job_title = None

        mock_base_result = MagicMock()
        mock_base_result.fetchone.return_value = mock_base_row
        mock_session.execute.return_value = mock_base_result

        mock_client = AsyncMock()
        mock_client.update_contact.return_value = {
            "resourceName": "people/c123",
            "etag": "updated-etag",
        }

        with (
            patch(
                "worker._load_full_contact",
                new_callable=AsyncMock,
                return_value={
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                    "important_dates": [],
                },
            ),
            patch(
                "worker._transform_contact_to_google_person",
                return_value={"names": [{"givenName": "Jane", "familyName": "Doe"}]},
            ),
            patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert,
        ):
            result = await _push_contact_to_google_for_event(
                session=mock_session,
                client=mock_client,
                contact_id=42,
                sync_action="update",
                google_account_email="test@gmail.com",
                external_id="people/c123",
                version_hash="etag-old",
            )

        assert result["status"] == "updated"
        mock_client.update_contact.assert_called_once()
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_skipped_when_contact_not_in_db(self) -> None:
        """_push_contact_to_google_for_event returns skipped when contact not found."""
        from worker import _push_contact_to_google_for_event

        mock_session = AsyncMock()

        # Mock the base contact query returning None (deleted between event and processing)
        mock_base_result = MagicMock()
        mock_base_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_base_result

        mock_client = AsyncMock()

        result = await _push_contact_to_google_for_event(
            session=mock_session,
            client=mock_client,
            contact_id=42,
            sync_action="create",
            google_account_email="test@gmail.com",
            external_id=None,
            version_hash=None,
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "contact_not_found"
        mock_client.create_contact.assert_not_called()


class TestDeleteContactFromGoogleForEvent:
    """Verify _delete_contact_from_google_for_event works correctly."""

    @pytest.mark.asyncio
    async def test_deletes_and_cleans_up_sync_metadata(self) -> None:
        """Verify delete calls Google API and removes sync metadata."""
        from worker import _delete_contact_from_google_for_event

        mock_session = AsyncMock()
        mock_client = AsyncMock()

        result = await _delete_contact_from_google_for_event(
            session=mock_session,
            client=mock_client,
            contact_id=42,
            external_id="people/c123",
            google_account_email="test@gmail.com",
        )

        assert result["status"] == "deleted"
        assert result["external_id"] == "people/c123"
        mock_client.delete_contact.assert_called_once_with(resource_name="people/c123")
        # Verify sync metadata cleanup was called
        mock_session.execute.assert_called_once()


class TestInboundEchoGuard:
    """LOCAL-177: events the inbound Google sync caused are not pushed back.

    The inbound sync applies Google's data through ``ContactService``, which
    re-publishes the very contact events the worker now consumes. Without a
    guard, every pull would trigger a write back to Google for each sub-entity
    it touched. The journal handler already guards this way (``worker.py``'s
    ``INBOUND_SYNC_SOURCE`` check); contacts did not.
    """

    @pytest.mark.parametrize(
        "event_type",
        ["ContactCreated", "ContactUpdated", "TagAssigned", "ContactMethodAdded"],
    )
    @pytest.mark.asyncio
    async def test_inbound_sourced_event_is_not_pushed_back(
        self, event_type: str
    ) -> None:
        """An event carrying the inbound sync provenance is skipped outright."""
        from worker import process_contact_event

        mock_factory, mock_session = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with patch(
            "worker._push_contact_to_google_for_event", new_callable=AsyncMock
        ) as mock_push:
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type=event_type,
                event_data={"contact_id": 42, "source": "google_contacts"},
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "inbound_echo"
        mock_push.assert_not_called()
        # The guard runs before any database work, so no session is opened.
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_merge_from_inbound_sync_is_not_pushed_back(self) -> None:
        """The guard covers ContactMerged, which is handled before contact_id."""
        from worker import process_contact_event

        with patch(
            "worker._process_contact_merged_event", new_callable=AsyncMock
        ) as mock_merge:
            result = await process_contact_event(
                ctx=_make_ctx(),
                event_type="ContactMerged",
                event_data={"source": "google_contacts", "external_collisions": []},
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "inbound_echo"
        mock_merge.assert_not_called()

    @pytest.mark.parametrize("source", ["ui", "mcp", "system", "immich"])
    @pytest.mark.asyncio
    async def test_locally_sourced_event_is_pushed(self, source: str) -> None:
        """Any provenance other than the Google inbound sync still pushes."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "created"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactUpdated",
                event_data={"contact_id": 42, "source": source},
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_without_source_is_pushed(self) -> None:
        """A missing ``source`` must not be mistaken for an inbound echo."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "created"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactUpdated",
                event_data={"contact_id": 42},
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()


class TestNewlyRoutedContactEvents:
    """LOCAL-177: the sub-entity events that were previously dropped.

    Each pushes the whole contact, exactly as ``ContactUpdated`` does — the
    event only has to say which contact changed.
    """

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
    @pytest.mark.asyncio
    async def test_sub_entity_event_pushes_the_contact(self, event_type: str) -> None:
        """A sub-entity change pushes the linked contact's current state."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "updated"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type=event_type,
                event_data={"contact_id": 42, "source": "ui"},
            )

        assert result["status"] == "success"
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args[1]
        assert call_kwargs["contact_id"] == 42
        assert call_kwargs["sync_action"] == "update"
        assert call_kwargs["external_id"] == "people/c123"


class TestEventPushSendsTagMemberships:
    """LOCAL-177: the event path never built a Google contact-group mapping.

    Without one ``_transform_contact_to_google_person`` omits ``memberships``
    entirely, so a tag change could not reach Google even once the event was
    routed. The mapping is resolved per Google account, creating any group a
    local tag needs.
    """

    @pytest.mark.asyncio
    async def test_push_receives_a_group_mapping(self) -> None:
        """process_contact_event resolves the mapping and hands it to the push."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._load_tag_names_for_contact",
                new_callable=AsyncMock,
                return_value=["Friends"],
            ),
            patch(
                "worker._resolve_group_mapping_for_tags",
                new_callable=AsyncMock,
                return_value={"Friends": "contactGroups/abc123"},
            ) as mock_resolve,
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "updated"},
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="TagAssigned",
                event_data={"contact_id": 42, "source": "ui"},
            )

        assert result["status"] == "success"
        assert mock_resolve.call_args[1]["tag_names"] == ["Friends"]
        assert mock_push.call_args[1]["group_name_to_resource"] == {
            "Friends": "contactGroups/abc123"
        }

    @pytest.mark.asyncio
    async def test_delete_event_resolves_no_group_mapping(self) -> None:
        """A delete needs no groups, so it makes no contactGroups API calls."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._resolve_group_mapping_for_tags", new_callable=AsyncMock
            ) as mock_resolve,
            patch(
                "worker._delete_contact_from_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "deleted"},
            ),
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactDeleted",
                event_data={"contact_id": 42, "source": "ui"},
            )

        assert result["status"] == "success"
        mock_resolve.assert_not_called()


class TestResolveGroupMappingForTags:
    """The shared tag-name → Google group resolution used by both push paths."""

    @pytest.mark.asyncio
    async def test_returns_reverse_mapping_and_creates_missing_groups(self) -> None:
        """Existing groups are reversed by name; a missing one is created."""
        from worker import _resolve_group_mapping_for_tags

        mock_client = AsyncMock()

        with (
            patch(
                "worker._fetch_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/abc123": "Friends"},
            ),
            patch(
                "worker._ensure_google_groups_exist",
                new_callable=AsyncMock,
                return_value={
                    "Friends": "contactGroups/abc123",
                    "Work": "contactGroups/new999",
                },
            ) as mock_ensure,
        ):
            result = await _resolve_group_mapping_for_tags(
                client=mock_client, tag_names=["Friends", "Work"]
            )

        assert result == {
            "Friends": "contactGroups/abc123",
            "Work": "contactGroups/new999",
        }
        assert mock_ensure.call_args[1]["existing_groups"] == {
            "Friends": "contactGroups/abc123"
        }

    @pytest.mark.asyncio
    async def test_no_tags_still_returns_a_mapping_so_memberships_are_sent(
        self,
    ) -> None:
        """An empty mapping is not "no mapping": it clears stale tag groups.

        The caller passes the result through to the transform, where a present
        (even empty) mapping means memberships are included in the update mask.
        """
        from worker import _resolve_group_mapping_for_tags

        with (
            patch(
                "worker._fetch_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "worker._ensure_google_groups_exist", new_callable=AsyncMock
            ) as mock_ensure,
        ):
            result = await _resolve_group_mapping_for_tags(
                client=AsyncMock(), tag_names=[]
            )

        assert result == {}
        # Nothing to create, so no group-creation round trip.
        mock_ensure.assert_not_called()


class TestGroupLookupFailureIsNotDestructive:
    """Greptile P1 on #1549: a swallowed listing failure stripped tag groups.

    ``_build_contact_group_mapping`` logs and returns a partial (often empty)
    mapping when ``contactGroups.list`` fails. Fed into the event push, every
    tag then looked groupless, so the update — which replaces ``memberships``
    wholesale — removed the contact from all its tag groups, and the
    swallowed error meant the event was acknowledged and never retried.
    """

    @pytest.mark.asyncio
    async def test_resolver_raises_when_group_listing_fails(self) -> None:
        """A failed listing propagates instead of looking like "no groups"."""
        from worker import _resolve_group_mapping_for_tags

        mock_client = AsyncMock()
        mock_client.list_contact_groups.side_effect = RuntimeError("503")

        with patch(
            "worker._ensure_google_groups_exist", new_callable=AsyncMock
        ) as mock_ensure:
            with pytest.raises(RuntimeError, match="503"):
                await _resolve_group_mapping_for_tags(
                    client=mock_client, tag_names=["Friends"]
                )

        # Groups that merely *looked* absent must not be re-created.
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolver_raises_when_a_later_page_fails(self) -> None:
        """A partial listing is as dangerous as an empty one."""
        from worker import _resolve_group_mapping_for_tags

        mock_client = AsyncMock()
        mock_client.list_contact_groups.side_effect = [
            {
                "contactGroups": [
                    {
                        "resourceName": "contactGroups/abc123",
                        "name": "Friends",
                        "formattedName": "Friends",
                    }
                ],
                "nextPageToken": "page-2",
            },
            RuntimeError("503 on page 2"),
        ]

        with pytest.raises(RuntimeError, match="page 2"):
            await _resolve_group_mapping_for_tags(
                client=mock_client, tag_names=["Friends"]
            )

    @pytest.mark.asyncio
    async def test_event_is_left_for_retry_and_nothing_is_pushed(self) -> None:
        """process_contact_event raises, so the stream redelivers the event."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
            tag_names=["Friends"],
        )

        with (
            patch(
                "worker._resolve_group_mapping_for_tags",
                new_callable=AsyncMock,
                side_effect=RuntimeError("503"),
            ),
            patch(
                "worker._push_contact_to_google_for_event", new_callable=AsyncMock
            ) as mock_push,
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            with pytest.raises(RuntimeError, match="503"):
                await process_contact_event(
                    ctx=_make_ctx(mock_factory),
                    event_type="TagAssigned",
                    event_data={"contact_id": 42, "source": "ui"},
                )

        mock_push.assert_not_called()


class TestUnresolvedTagGroupsOnTheEventPath:
    """Augment review of #1549: a failed group *creation* was swallowed.

    ``_ensure_google_groups_exist`` logs a ``create_contact_group`` failure and
    returns a mapping without that tag. The event push then succeeded without
    the membership, advanced ``last_synced_at`` and acknowledged the event, so
    the tag never reached Google until the contact changed again.

    The event path now requires every tag to resolve and raises otherwise, so
    the stream redelivers the event (bounded by the consumer's dead-letter
    limit). The cron path stays tolerant: a tag Google persistently rejects
    must not block every other contact's push.
    """

    @pytest.mark.asyncio
    async def test_strict_resolution_raises_for_a_tag_left_unmapped(self) -> None:
        from worker import UnresolvedTagGroupsError, _resolve_group_mapping_for_tags

        with (
            patch(
                "worker._fetch_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/abc123": "Friends"},
            ),
            patch(
                "worker._ensure_google_groups_exist",
                new_callable=AsyncMock,
                # "Work" could not be created, so it is missing from the result.
                return_value={"Friends": "contactGroups/abc123"},
            ),
        ):
            with pytest.raises(UnresolvedTagGroupsError, match="Work"):
                await _resolve_group_mapping_for_tags(
                    client=AsyncMock(),
                    tag_names=["Friends", "Work"],
                    require_all_tags=True,
                )

    @pytest.mark.asyncio
    async def test_tolerant_resolution_returns_the_partial_mapping(self) -> None:
        """The default keeps the cron path's skip-and-continue behaviour."""
        from worker import _resolve_group_mapping_for_tags

        with (
            patch(
                "worker._fetch_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/abc123": "Friends"},
            ),
            patch(
                "worker._ensure_google_groups_exist",
                new_callable=AsyncMock,
                return_value={"Friends": "contactGroups/abc123"},
            ),
        ):
            result = await _resolve_group_mapping_for_tags(
                client=AsyncMock(), tag_names=["Friends", "Work"]
            )

        assert result == {"Friends": "contactGroups/abc123"}

    @pytest.mark.asyncio
    async def test_case_variant_group_counts_as_resolved(self) -> None:
        """Tags match groups case-insensitively, as the membership transform does."""
        from worker import _resolve_group_mapping_for_tags

        with (
            patch(
                "worker._fetch_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/abc123": "Friends"},
            ),
            patch(
                "worker._ensure_google_groups_exist",
                new_callable=AsyncMock,
                return_value={"Friends": "contactGroups/abc123"},
            ),
        ):
            result = await _resolve_group_mapping_for_tags(
                client=AsyncMock(), tag_names=["friends"], require_all_tags=True
            )

        assert result == {"Friends": "contactGroups/abc123"}

    @pytest.mark.asyncio
    async def test_event_path_requires_every_tag_to_resolve(self) -> None:
        """process_contact_event opts into strict resolution."""
        from worker import process_contact_event

        mock_sync_row = MagicMock()
        mock_sync_row.external_id = "people/c123"
        mock_sync_row.version_hash = "etag-old"

        mock_factory, _ = _mock_session_factory(
            sync_row=mock_sync_row,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
            tag_names=["Friends"],
        )

        with (
            patch(
                "worker._resolve_group_mapping_for_tags",
                new_callable=AsyncMock,
                return_value={"Friends": "contactGroups/abc123"},
            ) as mock_resolve,
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "updated"},
            ),
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="TagAssigned",
                event_data={"contact_id": 42, "source": "ui"},
            )

        assert mock_resolve.call_args[1]["require_all_tags"] is True


class TestEventPushTakesTheContactLock:
    """Greptile review of #1551: the event path and the cron push can race.

    Both could read "no sync link" for a new contact and both create it in
    Google. The event path takes the per-contact push lock *before* it reads the
    link, so it sees a link the cron committed while it waited.
    """

    @pytest.mark.asyncio
    async def test_lock_is_taken_before_the_link_is_read(self) -> None:
        from worker import process_contact_event

        mock_factory, mock_session = _mock_session_factory(
            sync_row=None,
            users=[MagicMock(user_id="1", google_account_email="test@gmail.com")],
        )

        with (
            patch(
                "worker._push_contact_to_google_for_event",
                new_callable=AsyncMock,
                return_value={"status": "created"},
            ),
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=_google_client()),
        ):
            await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactCreated",
                event_data={"contact_id": 42, "source": "ui"},
            )

        first_sql, first_params = mock_session.execute.call_args_list[0][0]
        second_sql = str(mock_session.execute.call_args_list[1][0][0])
        assert "pg_advisory_xact_lock" in str(first_sql)
        assert first_params == {"key": "google-contact-push:42"}
        assert "FROM sync_metadata" in second_sql
