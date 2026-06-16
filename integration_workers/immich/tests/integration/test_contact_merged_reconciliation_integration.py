"""Integration tests for the Immich ContactMerged handler against a real DB.

A contact merge that collides on Immich (both contacts linked to an Immich
person) surfaces the clash on ``ContactMerged.external_collisions``. Because the
Immich API exposes no person-delete, the worker keeps the survivor's link and
unlinks the source contact's orphaned *local* reference and ``sync_metadata``
(using ``source_external_id`` from the payload). It must not attempt a remote
delete and must acknowledge the event without error.

These tests exercise the real database via ``db_session`` (real
external_references / sync_metadata rows) with no Immich API involvement at all.
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
    db_session: AsyncSession, internal_id: int, external_id: str
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 retry_count, created_at, updated_at)
            VALUES
                (:cid, 'immich', :ext, 'etag', 'success', NOW(),
                 0, NOW(), NOW())
            """
        ),
        {"cid": internal_id, "ext": external_id},
    )


async def _seed_external_reference(
    db_session: AsyncSession, internal_id: int, external_id: str
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO external_references
                (internal_entity_type, internal_entity_id, external_system,
                 external_entity_type, external_entity_id)
            VALUES
                ('contact', :cid, 'immich', 'person', :ext)
            """
        ),
        {"cid": internal_id, "ext": external_id},
    )


async def _sync_metadata_external_ids(db_session: AsyncSession) -> set[str]:
    result = await db_session.execute(
        text(
            "SELECT external_id FROM sync_metadata WHERE integration_source = 'immich'"
        )
    )
    return {row.external_id for row in result.fetchall()}


async def _external_reference_ids(db_session: AsyncSession) -> set[str]:
    result = await db_session.execute(
        text(
            """
            SELECT external_entity_id FROM external_references
            WHERE external_system = 'immich' AND external_entity_type = 'person'
            """
        )
    )
    return {row.external_entity_id for row in result.fetchall()}


@pytest_asyncio.fixture
async def merge_setup(db_session: AsyncSession) -> AsyncSession:
    """Seed survivor and source Immich references plus sync_metadata.

    In production Phase 1 removes the source's local rows inline; we seed
    residual source rows here to deterministically prove the worker unlinks
    them (the handler is idempotent if they are already gone).
    """
    await _seed_sync_metadata(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
    await _seed_external_reference(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
    await _seed_sync_metadata(db_session, _SOURCE_CONTACT, _SOURCE_PERSON)
    await _seed_external_reference(db_session, _SOURCE_CONTACT, _SOURCE_PERSON)
    await db_session.flush()
    return db_session


@pytest.mark.asyncio
class TestContactMergedImmichReconciliation:
    """Real-DB coverage for the ContactMerged Immich reconciliation handler."""

    async def test_same_service_unlinks_source_keeps_survivor(
        self, merge_setup: AsyncSession
    ) -> None:
        """Same-service collision unlinks the source ref and its sync metadata."""
        db_session = merge_setup

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
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

        remaining_refs = await _external_reference_ids(db_session)
        assert _SOURCE_PERSON not in remaining_refs  # source reference unlinked
        assert _SURVIVOR_PERSON in remaining_refs  # survivor reference preserved

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
        assert {_SURVIVOR_PERSON, _SOURCE_PERSON} <= await _external_reference_ids(
            db_session
        )

    async def test_unlink_scoped_to_source_contact_preserves_other_owners(
        self, merge_setup: AsyncSession
    ) -> None:
        """A reference owned by a different contact is not collaterally unlinked.

        The DELETE is scoped to the source contact's internal entity, so even a
        (pathological) row sharing the source's external person id but owned by
        another contact survives — bounding the blast radius.
        """
        db_session = merge_setup
        other_contact = 99
        await _seed_external_reference(db_session, other_contact, _SOURCE_PERSON)
        await db_session.flush()

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        assert result["status"] == "success"

        # The other owner's reference for the same external id is preserved.
        owner_ids = await db_session.execute(
            text(
                """
                SELECT internal_entity_id FROM external_references
                WHERE external_system = 'immich'
                  AND external_entity_type = 'person'
                  AND external_entity_id = :ext
                """
            ),
            {"ext": _SOURCE_PERSON},
        )
        remaining_owners = {row.internal_entity_id for row in owner_ids.fetchall()}
        assert other_contact in remaining_owners  # unrelated owner untouched
        assert _SOURCE_CONTACT not in remaining_owners  # source owner unlinked

    async def test_idempotent_when_source_already_unlinked(
        self, db_session: AsyncSession
    ) -> None:
        """The real post-Phase-1 state (source rows gone) succeeds, no dead-letter."""
        # Only the survivor rows exist; the source was already cleaned inline.
        await _seed_sync_metadata(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
        await _seed_external_reference(db_session, _SURVIVOR_CONTACT, _SURVIVOR_PERSON)
        await db_session.flush()

        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactMerged",
            event_data={
                "survivor_contact_id": _SURVIVOR_CONTACT,
                "source_contact_id": _SOURCE_CONTACT,
                "external_collisions": [_immich_collision()],
            },
        )

        # No row to remove, but the handler still acknowledges successfully.
        assert result["status"] == "success"
        assert _SURVIVOR_PERSON in await _sync_metadata_external_ids(db_session)
        assert _SURVIVOR_PERSON in await _external_reference_ids(db_session)
