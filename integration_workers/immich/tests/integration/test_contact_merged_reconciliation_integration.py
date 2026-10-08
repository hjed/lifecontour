"""Integration tests for the Immich ContactMerged handler against a real DB.

A contact merge that collides on Immich (both contacts linked to an Immich
person) surfaces the clash on ``ContactMerged.external_collisions``. Because the
Immich API exposes no person-delete, the worker keeps the survivor's link and
unlinks the source contact's orphaned canonical ``sync_metadata`` link (using
``source_external_id`` from the payload). It must not attempt a remote delete and
must acknowledge the event without error.

Since ITER15-001 the handler cleans the canonical ``sync_metadata`` link only
(``external_references`` has been retired).

These tests exercise the real database via ``db_session`` with no Immich API
involvement at all.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_contact_event

_SURVIVOR_PERSON = "11111111-1111-1111-1111-111111111111"
_SOURCE_PERSON = "22222222-2222-2222-2222-222222222222"
_SURVIVOR_CONTACT = 1
_SOURCE_CONTACT = 2
# The merged contacts' owner.
_OWNER = "merge-owner"


def _session_factory(db_session: AsyncSession) -> Any:
    """Build a session_factory that yields the test's transactional session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return factory


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    return {"session_factory": _session_factory(db_session), "job_id": "evt-merge-it"}


def _immich_collision() -> dict[str, str]:
    return {
        "external_system": "immich",
        "external_entity_type": "person",
        "source_external_id": _SOURCE_PERSON,
        "survivor_external_id": _SURVIVOR_PERSON,
    }


async def _seed_sync_metadata(
    db_session: AsyncSession,
    internal_id: int,
    external_id: str,
    *,
    user_id: str = _OWNER,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 retry_count, created_at, updated_at)
            VALUES
                (:uid, :cid, 'immich', :ext, 'etag', 'success', NOW(),
                 0, NOW(), NOW())
            """
        ),
        {"uid": user_id, "cid": internal_id, "ext": external_id},
    )


async def _sync_metadata_external_ids(db_session: AsyncSession) -> set[str]:
    result = await db_session.execute(
        text(
            "SELECT external_id FROM sync_metadata WHERE integration_source = 'immich'"
        )
    )
    return {row.external_id for row in result.fetchall()}


@pytest_asyncio.fixture
async def merge_setup(db_session: AsyncSession) -> AsyncSession:
    """Seed survivor and source Immich ``sync_metadata`` links.

    In production Phase 1 removes the source's local link inline; we seed a
    residual source link here to deterministically prove the worker unlinks it
    (the handler is idempotent if it is already gone).
    """
    await _seed_sync_metadata(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
    await _seed_sync_metadata(db_session, _SOURCE_CONTACT, _SOURCE_PERSON)
    await db_session.flush()
    return db_session


@pytest.mark.asyncio
class TestContactMergedImmichReconciliation:
    """Real-DB coverage for the ContactMerged Immich reconciliation handler."""

    async def test_same_service_unlinks_source_keeps_survivor(
        self, merge_setup: AsyncSession
    ) -> None:
        """Same-service collision unlinks the source's canonical sync_metadata link."""
        db_session = merge_setup

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "user_id": _OWNER,
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        # Event acknowledged without error.
        assert result["status"] == "success"

        remaining_meta = await _sync_metadata_external_ids(db_session)
        assert _SOURCE_PERSON not in remaining_meta  # source sync_metadata cleaned
        assert _SURVIVOR_PERSON in remaining_meta  # survivor link preserved

    async def test_different_service_collision_leaves_immich_untouched(
        self, merge_setup: AsyncSession
    ) -> None:
        """A collision on a non-Immich service unlinks no Immich rows."""
        db_session = merge_setup

        google_collision = {
            "external_system": "google",
            "external_entity_type": "person",
            "source_external_id": "people/source123",
            "survivor_external_id": "people/survivor456",
        }

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "user_id": _OWNER,
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [google_collision],
            },
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_immich_collisions"

        # Both Immich links untouched by a Google-only collision.
        assert {_SURVIVOR_PERSON, _SOURCE_PERSON} <= await _sync_metadata_external_ids(
            db_session
        )

    async def test_idempotent_when_source_already_unlinked(
        self, db_session: AsyncSession
    ) -> None:
        """The real post-Phase-1 state (source link gone) succeeds, no dead-letter."""
        # Only the survivor link exists; the source was already cleaned inline.
        await _seed_sync_metadata(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
        await db_session.flush()

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "user_id": _OWNER,
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        # No row to remove, but the handler still acknowledges successfully.
        assert result["status"] == "success"
        assert _SURVIVOR_PERSON in await _sync_metadata_external_ids(db_session)


@pytest.mark.asyncio
class TestContactMergedIsScopedToTheOwner:
    """The unlink touches only the merged-away contact's own link."""

    async def test_same_person_linked_to_another_contact_is_left_alone(
        self, db_session: AsyncSession
    ) -> None:
        """Only the source contact's own link is unlinked, never another's."""
        other_contact = 99
        await _seed_sync_metadata(db_session, other_contact, _SOURCE_PERSON)
        await db_session.flush()

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "user_id": _OWNER,
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        assert result["status"] == "success"
        assert _SOURCE_PERSON in await _sync_metadata_external_ids(db_session)

    async def test_another_owners_link_is_left_alone(
        self, db_session: AsyncSession
    ) -> None:
        """A link another user holds for the same person and contact id (a
        mis-owned row) is not the merging owner's to unlink."""
        await _seed_sync_metadata(
            db_session, _SOURCE_CONTACT, _SOURCE_PERSON, user_id="someone-else"
        )
        await db_session.flush()

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "user_id": _OWNER,
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        assert result["status"] == "success"
        assert _SOURCE_PERSON in await _sync_metadata_external_ids(db_session)

    async def test_event_without_owner_leaves_links_alone(
        self, merge_setup: AsyncSession
    ) -> None:
        """No owner: the event is skipped and both links remain."""
        result = await process_contact_event(
            ctx=_ctx(merge_setup),
            event_type="ContactMerged",
            event_data={
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        assert result == {"status": "skipped", "reason": "no_owner"}
        assert {_SURVIVOR_PERSON, _SOURCE_PERSON} <= await _sync_metadata_external_ids(
            merge_setup
        )
