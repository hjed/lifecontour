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


def _mock_session_factory(
    sync_row: Any = None,
    users: list[Any] | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory with sync_metadata + user_google_auth results.

    The new code executes queries in this order:
      1. sync_metadata lookup (fetchone)
      2. user_google_auth lookup (fetchall)

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

    mock_session.execute.side_effect = [
        mock_sync_result,  # 1st call: sync_metadata
        mock_users_result,  # 2nd call: user_google_auth
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
            patch("worker.GoogleAPIClient"),
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
