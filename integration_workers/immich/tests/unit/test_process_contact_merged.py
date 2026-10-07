# ruff: noqa: E402
"""Unit tests for the Immich ContactMerged reconciliation handler.

A contact merge that collides on the same external service (both contacts
linked to Immich) surfaces the clash on ``ContactMerged.external_collisions``.
Because the Immich API exposes no person-delete, the worker keeps the
survivor's link and unlinks the source contact's orphaned *local* reference
and ``sync_metadata`` (keyed by ``source_external_id``) — it must never attempt
a remote delete and must not error on the event.

The local DB unlink itself is patched here; its real SQL is covered by the
integration tests.
"""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
        "/personal_management_test"
    )
os.environ.setdefault("ENCRYPTION_KEY", "testkey")

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.testing import make_session_factory_mock


def _make_ctx(session_factory: Any = None) -> dict[str, Any]:
    """Build a minimal ARQ-style context for the handler."""
    return {
        "session_factory": session_factory or MagicMock(),
        "job_id": "evt-merge-unit",
    }


def _mock_session_factory() -> tuple[MagicMock, AsyncMock]:
    """Build a mock session factory yielding a committable session.

    The Immich merge handler performs only local DELETEs (no user_google_auth
    style lookup and no remote client), so a single session that supports
    ``commit`` is sufficient when the per-collision unlink helper is patched.
    """
    factory = make_session_factory_mock()
    return factory, factory.session


# The owner every merged event below names.
OWNER = "owner-a"


_IMMICH_COLLISION = {
    "external_system": "immich",
    "external_entity_type": "person",
    "source_external_id": "person-source",
    "survivor_external_id": "person-survivor",
}


@pytest.mark.asyncio
class TestProcessContactMerged:
    """Verify ContactMerged unlinks the source's orphaned Immich reference."""

    async def test_unlinks_source_for_immich_collision(self) -> None:
        """A same-service (immich) collision unlinks exactly the source ref."""
        from worker import process_contact_event

        mock_factory, mock_session = _mock_session_factory()

        with patch(
            "worker._unlink_immich_reference_for_event",
            new_callable=AsyncMock,
            return_value={"status": "unlinked", "external_id": "person-source"},
        ) as mock_unlink:
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "user_id": OWNER,
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_IMMICH_COLLISION],
                },
            )

        assert result["status"] == "success"
        mock_unlink.assert_awaited_once()
        call_kwargs = mock_unlink.call_args.kwargs
        assert call_kwargs["external_id"] == "person-source"
        assert call_kwargs["contact_id"] == 2
        mock_session.commit.assert_awaited()

    async def test_skips_when_no_immich_collision(self) -> None:
        """A different-service (or empty) collision set unlinks nothing."""
        from worker import process_contact_event

        google_collision = {
            "external_system": "google",
            "external_entity_type": "person",
            "source_external_id": "people/source123",
            "survivor_external_id": "people/survivor456",
        }

        with patch(
            "worker._unlink_immich_reference_for_event",
            new_callable=AsyncMock,
        ) as mock_unlink:
            result = await process_contact_event(
                ctx=_make_ctx(),
                event_type="ContactMerged",
                event_data={
                    "user_id": OWNER,
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [google_collision],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_immich_collisions"
        mock_unlink.assert_not_awaited()

    async def test_skips_malformed_collision_missing_source_external_id(self) -> None:
        """A malformed collision (no source_external_id) is skipped, not errored.

        A bare ``KeyError`` here would fail the job and, after retries,
        dead-letter the event — which the acceptance criteria forbid.
        """
        from worker import process_contact_event

        malformed = {
            "external_system": "immich",
            "external_entity_type": "person",
            # source_external_id intentionally absent
            "survivor_external_id": "person-survivor",
        }

        with patch(
            "worker._unlink_immich_reference_for_event",
            new_callable=AsyncMock,
        ) as mock_unlink:
            result = await process_contact_event(
                ctx=_make_ctx(),
                event_type="ContactMerged",
                event_data={
                    "user_id": OWNER,
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [malformed],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_immich_collisions"
        mock_unlink.assert_not_awaited()

    async def test_skips_non_person_immich_collision(self) -> None:
        """An Immich collision for a non-person entity type is not unlinked."""
        from worker import process_contact_event

        non_person = {
            "external_system": "immich",
            "external_entity_type": "album",
            "source_external_id": "album-source",
            "survivor_external_id": "album-survivor",
        }

        with patch(
            "worker._unlink_immich_reference_for_event",
            new_callable=AsyncMock,
        ) as mock_unlink:
            result = await process_contact_event(
                ctx=_make_ctx(),
                event_type="ContactMerged",
                event_data={
                    "user_id": OWNER,
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [non_person],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_immich_collisions"
        mock_unlink.assert_not_awaited()

    async def test_does_not_require_contact_id(self) -> None:
        """ContactMerged (no contact_id) must not hit the missing-id error path."""
        from worker import process_contact_event

        result = await process_contact_event(
            ctx=_make_ctx(),
            event_type="ContactMerged",
            event_data={
                "user_id": OWNER,
                "survivor_contact_id": 1,
                "source_contact_id": 2,
                "external_collisions": [],
            },
        )

        # Empty collisions short-circuits to a skip — crucially NOT an error.
        assert result["status"] == "skipped"
        assert result["reason"] == "no_immich_collisions"

    async def test_does_not_construct_immich_api_client(self) -> None:
        """The handler must never build an Immich client (no remote delete)."""
        from worker import process_contact_event

        mock_factory, _ = _mock_session_factory()

        with (
            patch(
                "worker._unlink_immich_reference_for_event",
                new_callable=AsyncMock,
                return_value={"status": "unlinked", "external_id": "person-source"},
            ),
            patch("worker.ImmichApiClient") as mock_client_cls,
        ):
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "user_id": OWNER,
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_IMMICH_COLLISION],
                },
            )

        assert result["status"] == "success"
        mock_client_cls.create.assert_not_called()
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
class TestMergeIsScopedToTheOwner:
    """A merge event that names no owner unlinks nothing."""

    async def test_event_without_owner_unlinks_nothing(self) -> None:
        """No owner: skipped before any database work."""
        from worker import process_contact_event

        mock_factory, mock_session = _mock_session_factory()

        with patch(
            "worker._unlink_immich_reference_for_event", new_callable=AsyncMock
        ) as mock_unlink:
            result = await process_contact_event(
                ctx=_make_ctx(mock_factory),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_IMMICH_COLLISION],
                },
            )

        assert result == {"status": "skipped", "reason": "no_owner"}
        mock_unlink.assert_not_awaited()
        mock_factory.assert_not_called()
