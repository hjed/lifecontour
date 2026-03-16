"""Unit tests for inbound sync helpers (InboundSyncClassifier and InboundFieldMerger)."""

from datetime import UTC, datetime, timedelta

import pytest

from calendar_models import GoogleEvent, GoogleEventStartEnd
from inbound_sync import (
    InboundFieldMerger,
    InboundSyncAction,
    InboundSyncClassifier,
)


class TestInboundSyncClassifier:
    """Tests for InboundSyncClassifier.classify_inbound_event."""

    @pytest.fixture
    def classifier(self) -> InboundSyncClassifier:
        return InboundSyncClassifier()

    @pytest.fixture
    def sample_google_event(self) -> GoogleEvent:
        return GoogleEvent(  # type: ignore[call-arg]
            id="google-event-123",
            summary="Team Meeting",
            description="Weekly sync",
            status="confirmed",
            etag='"etag-new-abc"',
            start=GoogleEventStartEnd(  # type: ignore[call-arg]
                date_time="2026-03-20T10:00:00Z",
            ),
            end=GoogleEventStartEnd(  # type: ignore[call-arg]
                date_time="2026-03-20T11:00:00Z",
            ),
        )

    def test_classify_new_event_no_existing_link(
        self, classifier: InboundSyncClassifier, sample_google_event: GoogleEvent
    ) -> None:
        """New event with no existing link should be classified as CREATE_JOURNAL."""
        result = classifier.classify_inbound_event(
            google_event=sample_google_event,
            existing_link=None,
        )
        assert result == InboundSyncAction.CREATE_JOURNAL

    def test_classify_unchanged_event_same_etag(
        self, classifier: InboundSyncClassifier, sample_google_event: GoogleEvent
    ) -> None:
        """Event with same ETag as stored should be classified as SKIP_UNCHANGED."""
        existing_link = _make_link(
            external_version='"etag-new-abc"',
            sync_capability="bidirectional",
        )
        result = classifier.classify_inbound_event(
            google_event=sample_google_event,
            existing_link=existing_link,
        )
        assert result == InboundSyncAction.SKIP_UNCHANGED

    def test_classify_updated_event_different_etag(
        self, classifier: InboundSyncClassifier, sample_google_event: GoogleEvent
    ) -> None:
        """Event with different ETag and bidirectional link should be UPDATE_JOURNAL."""
        existing_link = _make_link(
            external_version='"etag-old-xyz"',
            sync_capability="bidirectional",
        )
        result = classifier.classify_inbound_event(
            google_event=sample_google_event,
            existing_link=existing_link,
        )
        assert result == InboundSyncAction.UPDATE_JOURNAL

    def test_classify_outbound_only_rejects_inbound(
        self, classifier: InboundSyncClassifier, sample_google_event: GoogleEvent
    ) -> None:
        """Link with outbound-only sync_capability should be SKIP_ONE_WAY."""
        existing_link = _make_link(
            external_version='"etag-old-xyz"',
            sync_capability="outbound",
        )
        result = classifier.classify_inbound_event(
            google_event=sample_google_event,
            existing_link=existing_link,
        )
        assert result == InboundSyncAction.SKIP_ONE_WAY

    def test_classify_cancelled_event(self, classifier: InboundSyncClassifier) -> None:
        """Cancelled event should be SKIP (Phase 3 handles deletion)."""
        cancelled_event = GoogleEvent(  # type: ignore[call-arg]
            id="google-event-cancelled",
            summary="Cancelled Meeting",
            status="cancelled",
            etag='"etag-cancelled"',
            start=GoogleEventStartEnd(date_time="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
            end=GoogleEventStartEnd(date_time="2026-03-20T11:00:00Z"),  # type: ignore[call-arg]
        )
        result = classifier.classify_inbound_event(
            google_event=cancelled_event,
            existing_link=None,
        )
        assert result == InboundSyncAction.SKIP_CANCELLED

    def test_classify_cancelled_event_with_existing_link(
        self, classifier: InboundSyncClassifier
    ) -> None:
        """Cancelled event with existing link should be CANCEL_JOURNAL."""
        cancelled_event = GoogleEvent(  # type: ignore[call-arg]
            id="google-event-cancelled",
            summary="Cancelled Meeting",
            status="cancelled",
            etag='"etag-cancelled"',
            start=GoogleEventStartEnd(date_time="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
            end=GoogleEventStartEnd(date_time="2026-03-20T11:00:00Z"),  # type: ignore[call-arg]
        )
        existing_link = _make_link(
            external_version='"etag-old"',
            sync_capability="bidirectional",
        )
        result = classifier.classify_inbound_event(
            google_event=cancelled_event,
            existing_link=existing_link,
        )
        assert result == InboundSyncAction.CANCEL_JOURNAL

    def test_classify_cancelled_event_with_outbound_only_link(
        self, classifier: InboundSyncClassifier
    ) -> None:
        """Cancelled event with outbound-only link should still be CANCEL_JOURNAL."""
        cancelled_event = GoogleEvent(  # type: ignore[call-arg]
            id="google-event-cancelled",
            summary="Cancelled Meeting",
            status="cancelled",
            etag='"etag-cancelled"',
            start=GoogleEventStartEnd(date_time="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
            end=GoogleEventStartEnd(date_time="2026-03-20T11:00:00Z"),  # type: ignore[call-arg]
        )
        existing_link = _make_link(
            external_version='"etag-old"',
            sync_capability="outbound",
        )
        result = classifier.classify_inbound_event(
            google_event=cancelled_event,
            existing_link=existing_link,
        )
        assert result == InboundSyncAction.CANCEL_JOURNAL


class TestInboundFieldMerger:
    """Tests for InboundFieldMerger.merge_fields."""

    @pytest.fixture
    def merger(self) -> InboundFieldMerger:
        return InboundFieldMerger()

    @pytest.fixture
    def existing_journal_data(self) -> dict:  # type: ignore[type-arg]
        return {
            "title": "Original Title",
            "content": "Original content written locally",
            "event_date_range_start": "2026-03-20T10:00:00+00:00",
            "event_date_range_end": "2026-03-20T11:00:00+00:00",
        }

    @pytest.fixture
    def inbound_journal_data(self) -> dict:  # type: ignore[type-arg]
        return {
            "title": "Updated From Google",
            "content": "Description changed in Google",
            "event_date_range_start": "2026-03-20T14:00:00+00:00",
            "event_date_range_end": "2026-03-20T15:00:00+00:00",
        }

    def test_merge_no_local_edits_overwrites_cleanly(
        self,
        merger: InboundFieldMerger,
        existing_journal_data: dict,  # type: ignore[type-arg]
        inbound_journal_data: dict,  # type: ignore[type-arg]
    ) -> None:
        """When journal.updated_at <= link.last_synced_at, inbound data overwrites."""
        last_synced_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        journal_updated_at = last_synced_at - timedelta(hours=1)

        result = merger.merge_fields(
            existing_data=existing_journal_data,
            inbound_data=inbound_journal_data,
            journal_updated_at=journal_updated_at,
            link_updated_at=last_synced_at,
        )

        assert result["title"] == "Updated From Google"
        assert result["content"] == "Description changed in Google"
        assert result["event_date_range_start"] == "2026-03-20T14:00:00+00:00"
        assert result["event_date_range_end"] == "2026-03-20T15:00:00+00:00"

    def test_merge_local_edits_preserves_title_content(
        self,
        merger: InboundFieldMerger,
        existing_journal_data: dict,  # type: ignore[type-arg]
        inbound_journal_data: dict,  # type: ignore[type-arg]
    ) -> None:
        """When journal.updated_at > link.last_synced_at, preserve local title/content."""
        last_synced_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        journal_updated_at = last_synced_at + timedelta(hours=2)

        result = merger.merge_fields(
            existing_data=existing_journal_data,
            inbound_data=inbound_journal_data,
            journal_updated_at=journal_updated_at,
            link_updated_at=last_synced_at,
        )

        # Local edits preserved
        assert result["title"] == "Original Title"
        assert result["content"] == "Original content written locally"
        # Time fields always updated from inbound
        assert result["event_date_range_start"] == "2026-03-20T14:00:00+00:00"
        assert result["event_date_range_end"] == "2026-03-20T15:00:00+00:00"

    def test_merge_always_updates_time_fields(
        self,
        merger: InboundFieldMerger,
        existing_journal_data: dict,  # type: ignore[type-arg]
        inbound_journal_data: dict,  # type: ignore[type-arg]
    ) -> None:
        """Time fields should always take inbound values regardless of local edits."""
        last_synced_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
        journal_updated_at = last_synced_at + timedelta(days=5)

        result = merger.merge_fields(
            existing_data=existing_journal_data,
            inbound_data=inbound_journal_data,
            journal_updated_at=journal_updated_at,
            link_updated_at=last_synced_at,
        )

        assert result["event_date_range_start"] == "2026-03-20T14:00:00+00:00"
        assert result["event_date_range_end"] == "2026-03-20T15:00:00+00:00"

    def test_merge_equal_timestamps_overwrites(
        self,
        merger: InboundFieldMerger,
        existing_journal_data: dict,  # type: ignore[type-arg]
        inbound_journal_data: dict,  # type: ignore[type-arg]
    ) -> None:
        """When updated_at == last_synced_at (no local edits), inbound overwrites."""
        synced_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)

        result = merger.merge_fields(
            existing_data=existing_journal_data,
            inbound_data=inbound_journal_data,
            journal_updated_at=synced_at,
            link_updated_at=synced_at,
        )

        assert result["title"] == "Updated From Google"
        assert result["content"] == "Description changed in Google"


class _FakeExternalEventLink:
    """Minimal stand-in for JournalExternalEventLink for testing."""

    def __init__(self, external_version: str, sync_capability: str) -> None:
        self.external_version = external_version
        self.sync_capability = sync_capability


def _make_link(external_version: str, sync_capability: str) -> _FakeExternalEventLink:
    return _FakeExternalEventLink(
        external_version=external_version,
        sync_capability=sync_capability,
    )
