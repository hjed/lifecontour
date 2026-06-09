"""Integration tests for ImmichAlbumOutboxEventProcessor.

Covers album-to-journal creation with the derived date range and
sync_metadata/external_reference links, idempotent re-sync, and field merge
protection (local edits preserved on re-sync).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.immich.album_outbox_event_processor import (
    EVENT_TYPE_IMMICH_ALBUM_CREATED,
    EVENT_TYPE_IMMICH_ALBUM_UPDATED,
    ImmichAlbumOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "album-test-user"
START = datetime(2026, 1, 15, 0, 0, 0, 0, tzinfo=UTC)
END = datetime(2026, 1, 17, 23, 59, 59, 999999, tzinfo=UTC)


def _processor(connection: AsyncConnection) -> ImmichAlbumOutboxEventProcessor:
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(connection),
    )
    return ImmichAlbumOutboxEventProcessor(
        journal_service=service, connection=connection
    )


def _event(
    event_type: str,
    *,
    album_id: str,
    version_hash: str,
    title: str = "Summer Trip",
    content: str = "An album",
    start: datetime = START,
    end: datetime = END,
    asset_count: int = 3,
    people: list[dict[str, str]] | None = None,
    shared_link_url: str | None = None,
) -> OutboxEvent:
    album_metadata: dict[str, object] = {
        "album_name": title,
        "asset_count": asset_count,
    }
    if people is not None:
        album_metadata["people"] = people
    if shared_link_url is not None:
        album_metadata["shared_link_url"] = shared_link_url
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_id="0",
        event_data={
            "integration_source": "immich_album",
            "external_id": album_id,
            "version_hash": version_hash,
            "sync_action": event_type.split(".")[1],
            "journal_data": {
                "user_id": USER_ID,
                "title": title,
                "content": content,
                "event_date_range_start": start.isoformat(),
                "event_date_range_end": end.isoformat(),
            },
            "album_metadata": album_metadata,
            "sync_timestamp": datetime.now(UTC).isoformat(),
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


async def _seed_contact_linked_to_person(
    connection: AsyncConnection, first_name: str, person_id: str
) -> int:
    """Create a contact and an Immich person→contact external reference."""
    contact_id = (
        await connection.execute(
            text("INSERT INTO contacts (first_name) VALUES (:n) RETURNING id"),
            {"n": first_name},
        )
    ).scalar()
    assert contact_id is not None
    await connection.execute(
        text("""
            INSERT INTO external_references (
                internal_entity_type, internal_entity_id, external_system,
                external_entity_type, external_entity_id, reference_data,
                created_at, updated_at
            ) VALUES (
                'contact', :cid, 'immich', 'person', :pid, '{}', now(), now()
            )
        """),
        {"cid": contact_id, "pid": person_id},
    )
    return int(contact_id)


async def _participant_ids(connection: AsyncConnection, journal_id: int) -> set[int]:
    result = await connection.execute(
        text("""
            SELECT contact_id FROM journal_contact_relationships
            WHERE journal_id = :jid AND relationship_type = 'PARTICIPANT'
        """),
        {"jid": journal_id},
    )
    return {row.contact_id for row in result.fetchall()}


async def _journal_row(connection: AsyncConnection, journal_id: int):
    result = await connection.execute(
        text("""
            SELECT title, content, event_date_range_start, event_date_range_end
            FROM journals WHERE id = :id
        """),
        {"id": journal_id},
    )
    return result.fetchone()


async def _album_ref(connection: AsyncConnection, album_id: str):
    result = await connection.execute(
        text("""
            SELECT internal_entity_id, reference_data, updated_at
            FROM external_references
            WHERE external_system = 'immich'
              AND external_entity_type = 'album'
              AND external_entity_id = :id
        """),
        {"id": album_id},
    )
    return result.fetchone()


@pytest.mark.asyncio
async def test_create_album_journal_sets_date_range_and_links(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A created event makes a journal with the date range + sync links."""
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    result = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )

    assert result["status"] == "created"
    journal_id = result["journal_id"]

    row = await _journal_row(async_connection, journal_id)
    assert row.title == "Summer Trip"
    assert row.event_date_range_start == START
    assert row.event_date_range_end == END

    # sync_metadata link
    meta = (
        await async_connection.execute(
            text("""
                SELECT internal_id, version_hash FROM sync_metadata
                WHERE integration_source = 'immich_album' AND external_id = :id
            """),
            {"id": album_id},
        )
    ).fetchone()
    assert meta is not None
    assert meta.internal_id == journal_id
    assert meta.version_hash == "v1"

    # external_reference link with album metadata
    ref = (
        await async_connection.execute(
            text("""
                SELECT internal_entity_id, reference_data FROM external_references
                WHERE external_system = 'immich'
                  AND external_entity_type = 'album'
                  AND external_entity_id = :id
            """),
            {"id": album_id},
        )
    ).fetchone()
    assert ref is not None
    assert ref.internal_entity_id == journal_id
    assert json.loads(ref.reference_data)["album_name"] == "Summer Trip"

    # PHOTO_ALBUM is detectable via the repository
    types = await SqlJournalRepository(async_connection).get_types(journal_id)
    assert "PHOTO_ALBUM" in types


@pytest.mark.asyncio
async def test_resync_unchanged_version_hash_is_skipped(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """Re-syncing the same album version is a no-op (idempotent)."""
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    result = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_UPDATED, album_id=album_id, version_hash="v1")
    )

    assert result["status"] == "skipped"
    assert result["journal_id"] == journal_id


@pytest.mark.asyncio
async def test_resync_updates_when_not_locally_edited(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A changed album version updates the journal when not edited locally."""
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    new_end = END + timedelta(days=1)
    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            title="Renamed Trip",
            end=new_end,
        )
    )

    assert result["status"] == "updated"
    row = await _journal_row(async_connection, journal_id)
    assert row.title == "Renamed Trip"
    assert row.event_date_range_end == new_end

    # The emitted JournalUpdated event uses the repo-wide changed_fields
    # convention (a single ``event_date_range`` key), not ``_start`` / ``_end``.
    evt = (
        await async_connection.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'JournalUpdated' AND aggregate_id = :jid
                ORDER BY id DESC LIMIT 1
            """),
            {"jid": journal_id},
        )
    ).fetchone()
    assert evt is not None
    changed_fields = json.loads(evt.event_data).get("changed_fields", {})
    assert "event_date_range" in changed_fields
    assert "event_date_range_start" not in changed_fields


@pytest.mark.asyncio
async def test_resync_preserves_locally_edited_fields(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """Local edits to title/content/date range survive a re-sync."""
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    # Simulate a local edit AFTER the last sync: bump journal.updated_at past
    # the external reference's updated_at and change the title locally.
    await async_connection.execute(
        text("""
            UPDATE journals
            SET title = 'Local Title', updated_at = now() + interval '1 hour'
            WHERE id = :id
        """),
        {"id": journal_id},
    )

    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            title="Immich Title",
        )
    )

    assert result["status"] == "protected"
    row = await _journal_row(async_connection, journal_id)
    assert row.title == "Local Title"

    # The album version is still recorded so it is not reprocessed endlessly.
    meta = (
        await async_connection.execute(
            text("""
                SELECT version_hash FROM sync_metadata
                WHERE integration_source = 'immich_album' AND external_id = :id
            """),
            {"id": album_id},
        )
    ).fetchone()
    assert meta is not None
    assert meta.version_hash == "v2"


@pytest.mark.asyncio
async def test_protected_resync_refreshes_display_metadata_but_keeps_anchor(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A protected re-sync refreshes album display data without losing protection.

    The album's display metadata (name / asset count) must stay current even
    when the journal's title/content/date are protected, but the merge anchor
    (external_reference.updated_at) must NOT advance, so the journal remains
    protected on subsequent syncs.
    """
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            asset_count=3,
        )
    )
    journal_id = created["journal_id"]
    anchor_before = (await _album_ref(async_connection, album_id)).updated_at

    # Local edit after the last sync.
    await async_connection.execute(
        text("""
            UPDATE journals
            SET title = 'Local Title', updated_at = now() + interval '1 hour'
            WHERE id = :id
        """),
        {"id": journal_id},
    )

    # Album changed in Immich (new name + asset count) → protected re-sync.
    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            title="Renamed In Immich",
            asset_count=12,
        )
    )
    assert result["status"] == "protected"

    ref = await _album_ref(async_connection, album_id)
    # Display metadata refreshed despite protection...
    assert json.loads(ref.reference_data)["album_name"] == "Renamed In Immich"
    assert json.loads(ref.reference_data)["asset_count"] == 12
    # ...but the merge anchor was preserved (not advanced).
    assert ref.updated_at == anchor_before

    # A subsequent change is therefore still protected.
    result2 = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v3",
            title="Renamed Again",
        )
    )
    assert result2["status"] == "protected"
    assert (await _journal_row(async_connection, journal_id)).title == "Local Title"


@pytest.mark.asyncio
async def test_created_retry_without_external_reference_does_not_duplicate(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A retried create is idempotent even if only sync_metadata survives.

    If the external_reference row is missing but sync_metadata still links the
    album to a journal, re-processing a created event must update that journal
    rather than creating a duplicate.
    """
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    # Simulate a lost external_reference row (sync_metadata still present).
    await async_connection.execute(
        text("""
            DELETE FROM external_references
            WHERE external_system = 'immich'
              AND external_entity_type = 'album'
              AND external_entity_id = :id
        """),
        {"id": album_id},
    )

    # Re-send a created event with changed metadata.
    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v2",
            title="Retried",
        )
    )

    # Same journal updated, not a duplicate.
    assert result["journal_id"] == journal_id
    count = (
        await async_connection.execute(
            text("""
                SELECT count(*) AS n FROM sync_metadata
                WHERE integration_source = 'immich_album' AND external_id = :id
            """),
            {"id": album_id},
        )
    ).fetchone()
    assert count is not None
    assert count.n == 1

    journal_count = (
        await async_connection.execute(
            text("SELECT count(*) AS n FROM journals WHERE user_id = :u"),
            {"u": USER_ID},
        )
    ).fetchone()
    assert journal_count is not None
    assert journal_count.n == 1


@pytest.mark.asyncio
async def test_missing_link_anchor_protects_local_edits(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A re-sync with a missing link anchor must not overwrite local edits.

    If the album external_reference is lost, we cannot tell whether the journal
    was edited locally, so the safe default is to protect it (no data loss).
    """
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    # User edits the journal locally, then the link row is lost.
    await async_connection.execute(
        text("UPDATE journals SET title = 'Local Title' WHERE id = :id"),
        {"id": journal_id},
    )
    await async_connection.execute(
        text("""
            DELETE FROM external_references
            WHERE external_system = 'immich'
              AND external_entity_type = 'album'
              AND external_entity_id = :id
        """),
        {"id": album_id},
    )

    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            title="Immich Overwrite",
        )
    )

    assert result["status"] == "protected"
    assert (await _journal_row(async_connection, journal_id)).title == "Local Title"
    # The link anchor was re-established for subsequent syncs.
    assert await _album_ref(async_connection, album_id) is not None

    # The re-established anchor must be far-past (not "now"), so a *further*
    # album change still protects the local edit rather than overwriting it.
    result2 = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v3",
            title="Immich Overwrite Again",
        )
    )
    assert result2["status"] == "protected"
    assert (await _journal_row(async_connection, journal_id)).title == "Local Title"


@pytest.mark.asyncio
async def test_merge_protection_uses_the_anchor_for_the_target_journal(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """Merge protection must compare against this journal's own anchor.

    If a stray, newer external_reference exists for the same album (pointing at
    a different entity), the protection decision must still use the anchor of
    the journal actually being updated — not the newest row.
    """
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(EVENT_TYPE_IMMICH_ALBUM_CREATED, album_id=album_id, version_hash="v1")
    )
    journal_id = created["journal_id"]

    # Local edit after the last sync (advances journal.updated_at past anchor).
    await async_connection.execute(
        text("""
            UPDATE journals
            SET title = 'Local Title', updated_at = now() + interval '1 hour'
            WHERE id = :id
        """),
        {"id": journal_id},
    )

    # A stray, newer reference for the same album pointing at a different (here
    # non-existent) entity, with a far-future anchor that would defeat
    # protection if it were (incorrectly) selected.
    await async_connection.execute(
        text("""
            INSERT INTO external_references (
                internal_entity_type, internal_entity_id, external_system,
                external_entity_type, external_entity_id, reference_data,
                created_at, updated_at
            ) VALUES (
                'journal', 99999999, 'immich', 'album', :id, '{}',
                now(), now() + interval '1 day'
            )
        """),
        {"id": album_id},
    )

    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            title="Immich Overwrite",
        )
    )

    assert result["status"] == "protected"
    assert (await _journal_row(async_connection, journal_id)).title == "Local Title"


@pytest.mark.asyncio
async def test_album_with_tagged_people_creates_participants(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """Tagged Immich people resolve to contacts added as PARTICIPANTs."""
    album_id = str(uuid.uuid4())
    alice = await _seed_contact_linked_to_person(async_connection, "Alice", "p1")
    bob = await _seed_contact_linked_to_person(async_connection, "Bob", "p2")
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "p1", "name": "Alice"}, {"id": "p2", "name": "Bob"}],
        )
    )
    journal_id = created["journal_id"]

    assert await _participant_ids(async_connection, journal_id) == {alice, bob}
    # The immich-managed set is tracked in the album reference_data.
    ref = await _album_ref(async_connection, album_id)
    assert sorted(json.loads(ref.reference_data)["participant_contact_ids"]) == sorted(
        [alice, bob]
    )


@pytest.mark.asyncio
async def test_unresolved_person_creates_no_participant(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """An Immich person not linked to a contact produces no participant."""
    album_id = str(uuid.uuid4())
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "unlinked", "name": "Nobody"}],
        )
    )

    assert await _participant_ids(async_connection, created["journal_id"]) == set()


@pytest.mark.asyncio
async def test_resync_removed_tag_removes_participant(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """On a non-locally-edited journal, an untagged person is removed."""
    album_id = str(uuid.uuid4())
    alice = await _seed_contact_linked_to_person(async_connection, "Alice", "p1")
    bob = await _seed_contact_linked_to_person(async_connection, "Bob", "p2")
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "p1", "name": "Alice"}, {"id": "p2", "name": "Bob"}],
        )
    )
    journal_id = created["journal_id"]
    assert await _participant_ids(async_connection, journal_id) == {alice, bob}

    # Bob is untagged in Immich (new version hash); no local edit.
    await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            people=[{"id": "p1", "name": "Alice"}],
        )
    )

    assert await _participant_ids(async_connection, journal_id) == {alice}


@pytest.mark.asyncio
async def test_resync_locally_edited_is_add_only(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """On a locally-edited journal: new people added, untagged people kept."""
    album_id = str(uuid.uuid4())
    alice = await _seed_contact_linked_to_person(async_connection, "Alice", "p1")
    bob = await _seed_contact_linked_to_person(async_connection, "Bob", "p2")
    carol = await _seed_contact_linked_to_person(async_connection, "Carol", "p3")
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "p1", "name": "Alice"}, {"id": "p2", "name": "Bob"}],
        )
    )
    journal_id = created["journal_id"]

    # Local edit AFTER the last sync → merge-protected (add-only).
    await async_connection.execute(
        text("""
            UPDATE journals
            SET title = 'Local Title', updated_at = now() + interval '1 hour'
            WHERE id = :id
        """),
        {"id": journal_id},
    )

    # Immich drops Bob, adds Carol.
    await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            people=[{"id": "p1", "name": "Alice"}, {"id": "p3", "name": "Carol"}],
        )
    )

    # Carol added; Bob NOT removed (add-only under protection).
    assert await _participant_ids(async_connection, journal_id) == {alice, bob, carol}


@pytest.mark.asyncio
async def test_resync_does_not_remove_manual_participant(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A manually-added participant survives a full immich-people removal."""
    album_id = str(uuid.uuid4())
    alice = await _seed_contact_linked_to_person(async_connection, "Alice", "p1")
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "p1", "name": "Alice"}],
        )
    )
    journal_id = created["journal_id"]

    # A manual participant (not an Immich person) is added directly.
    manual = (
        await async_connection.execute(
            text("INSERT INTO contacts (first_name) VALUES ('Manual') RETURNING id")
        )
    ).scalar()
    await async_connection.execute(
        text("""
            INSERT INTO journal_contact_relationships
                (journal_id, contact_id, relationship_type)
            VALUES (:jid, :cid, 'PARTICIPANT')
        """),
        {"jid": journal_id, "cid": manual},
    )

    # Immich removes all tagged people.
    await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            people=[],
        )
    )

    participants = await _participant_ids(async_connection, journal_id)
    assert alice not in participants  # immich-managed → removed
    assert manual in participants  # manual → preserved


@pytest.mark.asyncio
async def test_shared_link_url_persisted_in_reference_data(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A shared link URL on the album is stored in reference_data."""
    album_id = str(uuid.uuid4())
    share_url = "https://immich.example.com/share/abc"
    processor = _processor(async_connection)

    await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            shared_link_url=share_url,
        )
    )

    ref = await _album_ref(async_connection, album_id)
    assert json.loads(ref.reference_data)["shared_link_url"] == share_url


@pytest.mark.asyncio
async def test_resync_tolerates_malformed_participant_contact_ids(
    async_connection: AsyncConnection,
    clean_database: None,  # noqa: ARG001
) -> None:
    """A corrupted participant_contact_ids in reference_data must not break sync."""
    album_id = str(uuid.uuid4())
    alice = await _seed_contact_linked_to_person(async_connection, "Alice", "p1")
    processor = _processor(async_connection)

    created = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            album_id=album_id,
            version_hash="v1",
            people=[{"id": "p1", "name": "Alice"}],
        )
    )
    journal_id = created["journal_id"]

    # Corrupt the stored immich-managed set with nulls / non-numeric values.
    ref = await _album_ref(async_connection, album_id)
    bad = json.loads(ref.reference_data)
    bad["participant_contact_ids"] = [alice, None, "x", True]
    await async_connection.execute(
        text("""
            UPDATE external_references SET reference_data = :rd
            WHERE external_system = 'immich' AND external_entity_type = 'album'
              AND external_entity_id = :id
        """),
        {"rd": json.dumps(bad), "id": album_id},
    )

    # Re-sync (new version hash) must succeed despite the malformed list.
    result = await processor.process_event(
        _event(
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            album_id=album_id,
            version_hash="v2",
            people=[{"id": "p1", "name": "Alice"}],
        )
    )

    assert result["status"] == "updated"
    assert await _participant_ids(async_connection, journal_id) == {alice}
