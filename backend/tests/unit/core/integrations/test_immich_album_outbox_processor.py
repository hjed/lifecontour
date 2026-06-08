"""Unit tests for ImmichAlbumOutboxEventProcessor pure logic.

Covers field merge protection (local-edit detection), journal building from
album payload data, reference_data construction, and participant reconciliation
(add always / remove only when not locally edited) — without a database.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import JournalContactRelationshipType
from core_shared.models.outbox_events import ImmichAlbumSyncEventData

from app.core.integrations.immich_album_outbox_event_processor import (
    ImmichAlbumOutboxEventProcessor,
)

PARTICIPANT = JournalContactRelationshipType.PARTICIPANT


class TestHasLocalEdits:
    """Merge-protection detection: journal.updated_at > link.updated_at."""

    def test_journal_edited_after_link_is_local_edit(self) -> None:
        link = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        journal = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, link) is True

    def test_journal_not_edited_since_sync_is_not_local_edit(self) -> None:
        link = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
        journal = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, link) is False

    def test_equal_timestamps_are_not_local_edit(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(ts, ts) is False

    def test_missing_link_timestamp_is_not_local_edit(self) -> None:
        journal = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        assert ImmichAlbumOutboxEventProcessor._has_local_edits(journal, None) is False


class TestBuildJournal:
    """Journal entity construction from album journal_data."""

    def test_builds_journal_with_event_date_range(self) -> None:
        journal_data = {
            "user_id": "user-1",
            "title": "Trip",
            "content": "An album",
            "event_date_range_start": "2026-01-15T00:00:00+00:00",
            "event_date_range_end": "2026-01-17T23:59:59+00:00",
        }
        journal = ImmichAlbumOutboxEventProcessor._build_journal(
            journal_data, journal_id=7
        )
        assert journal.id == 7
        assert journal.user_id == "user-1"
        assert journal.title == "Trip"
        assert journal.event_date_range.start == datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
        assert journal.event_date_range.end == datetime(
            2026, 1, 17, 23, 59, 59, tzinfo=UTC
        )


class TestReferenceData:
    """Album external reference display-metadata construction."""

    def _payload(self, **metadata: object) -> ImmichAlbumSyncEventData:
        return ImmichAlbumSyncEventData(
            external_id="album-1",
            version_hash="v1",
            sync_action="created",
            journal_data={
                "user_id": "u",
                "title": "t",
                "content": "",
                "event_date_range_start": "2026-01-15T00:00:00+00:00",
                "event_date_range_end": "2026-01-15T23:59:59+00:00",
            },
            album_metadata=dict(metadata),
            sync_timestamp=datetime.now(UTC).isoformat(),
        )

    def test_includes_album_id_and_present_metadata(self) -> None:
        payload = self._payload(album_name="Trip", asset_count=3)
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert data["album_id"] == "album-1"
        assert data["album_name"] == "Trip"
        assert data["asset_count"] == 3

    def test_omits_missing_metadata_fields(self) -> None:
        payload = self._payload(album_name="Trip")
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert "album_url" not in data
        assert "thumbnail_asset_id" not in data

    def test_includes_shared_link_url_when_present(self) -> None:
        payload = self._payload(
            album_name="Trip", shared_link_url="https://immich.example.com/share/abc"
        )
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert data["shared_link_url"] == "https://immich.example.com/share/abc"

    def test_omits_shared_link_url_when_absent(self) -> None:
        payload = self._payload(album_name="Trip")
        data = ImmichAlbumOutboxEventProcessor._reference_data(payload)
        assert "shared_link_url" not in data


def _rel(contact_id: int) -> MagicMock:
    rel = MagicMock()
    rel.contact_id = contact_id
    return rel


def _participant_processor(
    *, resolved: dict[str, int], existing_contact_ids: list[int]
) -> tuple[ImmichAlbumOutboxEventProcessor, AsyncMock]:
    """Build a processor with mocked participant repos for ``_sync_participants``.

    Returns the processor and the relationship-repo mock (so assertions can read
    ``create``/``delete`` call args without fighting the repo's real types).
    """
    processor = ImmichAlbumOutboxEventProcessor(
        journal_service=MagicMock(), connection=AsyncMock()
    )
    ext_ref = AsyncMock()
    ext_ref.get_contact_ids_by_immich_person_ids = AsyncMock(return_value=resolved)
    relationship = AsyncMock()
    relationship.get_by_journal_and_type = AsyncMock(
        return_value=[_rel(cid) for cid in existing_contact_ids]
    )
    processor.ext_ref_repo = ext_ref
    processor.relationship_repo = relationship
    return processor, relationship


def _people_payload(*person_ids: str) -> ImmichAlbumSyncEventData:
    return ImmichAlbumSyncEventData(
        external_id="album-1",
        version_hash="v1",
        sync_action="updated",
        journal_data={
            "user_id": "u",
            "title": "t",
            "content": "",
            "event_date_range_start": "2026-01-15T00:00:00+00:00",
            "event_date_range_end": "2026-01-15T23:59:59+00:00",
        },
        album_metadata={
            "people": [{"id": pid, "name": pid.upper()} for pid in person_ids]
        },
        sync_timestamp=datetime.now(UTC).isoformat(),
    )


@pytest.mark.asyncio
class TestSyncParticipants:
    """Participant reconciliation: add always; remove only when not protected."""

    async def test_resolves_people_and_adds_participants(self) -> None:
        processor, relationship = _participant_processor(
            resolved={"p1": 1, "p2": 2}, existing_contact_ids=[]
        )

        result = await processor._sync_participants(
            7, _people_payload("p1", "p2"), {}, has_local_edits=False
        )

        created = {c.args[0].contact_id for c in relationship.create.call_args_list}
        assert created == {1, 2}
        # All created as PARTICIPANT.
        for c in relationship.create.call_args_list:
            assert c.args[0].relationship_type == PARTICIPANT
        relationship.delete.assert_not_called()
        assert result == [1, 2]

    async def test_skips_unresolved_people(self) -> None:
        # p3 has no contact link → omitted from the resolved map.
        processor, relationship = _participant_processor(
            resolved={"p1": 1}, existing_contact_ids=[]
        )

        result = await processor._sync_participants(
            7, _people_payload("p1", "p3"), {}, has_local_edits=False
        )

        created = {c.args[0].contact_id for c in relationship.create.call_args_list}
        assert created == {1}
        assert result == [1]

    async def test_does_not_recreate_existing_participant(self) -> None:
        processor, relationship = _participant_processor(
            resolved={"p1": 1, "p2": 2}, existing_contact_ids=[1]
        )

        await processor._sync_participants(
            7,
            _people_payload("p1", "p2"),
            {"participant_contact_ids": [1]},
            has_local_edits=False,
        )

        created = {c.args[0].contact_id for c in relationship.create.call_args_list}
        # Only the genuinely-new contact 2 is inserted (1 already present).
        assert created == {2}

    async def test_removes_gone_participants_when_not_protected(self) -> None:
        processor, relationship = _participant_processor(
            resolved={"p1": 1}, existing_contact_ids=[1, 2]
        )

        result = await processor._sync_participants(
            7,
            _people_payload("p1"),
            {"participant_contact_ids": [1, 2]},
            has_local_edits=False,
        )

        deleted = {c.args[1] for c in relationship.delete.call_args_list}
        assert deleted == {2}
        # Removal targets PARTICIPANT.
        for c in relationship.delete.call_args_list:
            assert c.args[2] == PARTICIPANT
        assert result == [1]

    async def test_add_only_when_locally_edited(self) -> None:
        # Locally edited: a newly-tagged person is still added, but the person
        # who was untagged in Immich is NOT removed.
        processor, relationship = _participant_processor(
            resolved={"p3": 3}, existing_contact_ids=[1, 2]
        )

        result = await processor._sync_participants(
            7,
            _people_payload("p3"),
            {"participant_contact_ids": [1, 2]},
            has_local_edits=True,
        )

        created = {c.args[0].contact_id for c in relationship.create.call_args_list}
        assert created == {3}
        relationship.delete.assert_not_called()
        # Tracked set keeps the un-removed immich participants plus the new one.
        assert result == [1, 2, 3]

    async def test_preserves_manual_participant_not_in_immich_set(self) -> None:
        # c9 is a manual participant (never in the immich-managed set). A full
        # removal of immich people must not touch it.
        processor, relationship = _participant_processor(
            resolved={}, existing_contact_ids=[1, 9]
        )

        result = await processor._sync_participants(
            7,
            _people_payload(),
            {"participant_contact_ids": [1]},
            has_local_edits=False,
        )

        deleted = {c.args[1] for c in relationship.delete.call_args_list}
        assert deleted == {1}  # only the immich-managed contact is removed
        assert 9 not in deleted
        assert result == []

    async def test_tolerates_malformed_participant_contact_ids(self) -> None:
        # A corrupted reference_data list (nulls / non-numeric / wrong types)
        # must not break album sync — only clean integer ids are honoured.
        processor, relationship = _participant_processor(
            resolved={"p1": 1}, existing_contact_ids=[1, 2]
        )

        result = await processor._sync_participants(
            7,
            _people_payload("p1"),
            {"participant_contact_ids": [1, 2, None, "3", "x", True]},
            has_local_edits=False,
        )

        # Prev coerces to {1, 2, 3}; desired is {1} → remove {2, 3}.
        deleted = {c.args[1] for c in relationship.delete.call_args_list}
        assert deleted == {2, 3}
        assert result == [1]


class TestCoerceContactIds:
    """Defensive parsing of stored participant_contact_ids."""

    def test_keeps_ints_and_numeric_strings_drops_the_rest(self) -> None:
        assert ImmichAlbumOutboxEventProcessor._coerce_contact_ids(
            [1, "2", None, "x", True, 3.5, -4]
        ) == {1, 2, -4}

    def test_non_list_returns_empty_set(self) -> None:
        assert ImmichAlbumOutboxEventProcessor._coerce_contact_ids(None) == set()
        assert ImmichAlbumOutboxEventProcessor._coerce_contact_ids("nope") == set()
