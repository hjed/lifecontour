"""
Unit tests for outbox event payload models.

Tests that each Pydantic payload model correctly validates, serializes,
and rejects invalid data — ensuring the publisher/consumer contract is
well-defined.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import (
    ContactSyncEventData,
    FitnessDurationCorrectedData,
    ImmichAlbumSyncEventData,
    JournalSeriesCancelledEventData,
    JournalStatusEventData,
    JournalSyncEventData,
    MatchDetectionEventData,
    OutboxEventData,
    SyncCompletedEventData,
    parse_outbox_event_data,
)


@pytest.fixture
def immich_album_data() -> dict[str, Any]:
    """Minimal valid ImmichAlbumSyncEventData payload."""
    return {
        "external_id": "album-uuid-1",
        "version_hash": "hash-1",
        "sync_action": "created",
        "journal_data": {
            "user_id": "user-1",
            "title": "Trip",
            "content": "An album",
            "event_date_range_start": datetime.now(UTC).isoformat(),
            "event_date_range_end": datetime.now(UTC).isoformat(),
        },
        "album_metadata": {"album_name": "Trip", "asset_count": 3},
        "sync_timestamp": datetime.now(UTC).isoformat(),
    }


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def contact_sync_data() -> dict[str, Any]:
    """Minimal valid ContactSyncEventData payload."""
    return {
        "integration_source": "google",
        "external_id": "people/c123456789",
        "contact_data": {"first_name": "Alice", "last_name": "Smith"},
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_type": "created",
        "etag": "abc123",
        "user_id": "user-1",
    }


@pytest.fixture
def sync_completed_data() -> dict[str, Any]:
    """Minimal valid SyncCompletedEventData payload."""
    return {
        "integration_source": "google",
        "google_account_email": "user@gmail.com",
        "metrics": {"contacts_processed": 10, "contacts_created": 3},
        "completed_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def journal_sync_data() -> dict[str, Any]:
    """Minimal valid JournalSyncEventData payload."""
    return {
        "integration_source": "google",
        "external_event_id": "google:evt-123",
        "calendar_id": "00000000-0000-0000-0000-000000000001",
        "journal_data": {
            "user_id": "user-1",
            "title": "Meeting",
            "content": "Notes here",
            "event_date_range_start": "2024-01-15T10:00:00+00:00",
            "event_date_range_end": "2024-01-15T11:00:00+00:00",
        },
        "calendar_info_data": {
            "calendar_id": "00000000-0000-0000-0000-000000000001",
            "is_all_day": False,
        },
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_action": "created",
        "etag": None,
        "existing_journal_id": None,
        "contact_relationships": [],
    }


@pytest.fixture
def match_detection_data() -> dict[str, Any]:
    """Minimal valid MatchDetectionEventData payload."""
    return {
        "journal_id": 42,
        "user_id": "user-1",
        "journal_title": "Team Standup",
        "journal_content": "Discussed sprint progress",
        "event_date_range_start": "2024-01-15T09:00:00+00:00",
        "event_date_range_end": "2024-01-15T09:15:00+00:00",
        "created_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def journal_status_data() -> dict[str, Any]:
    """Minimal valid JournalStatusEventData payload."""
    return {
        "external_event_id": "google:evt-456",
        "calendar_id": "00000000-0000-0000-0000-000000000001",
        "existing_journal_id": 10,
    }


# ── ContactSyncEventData Tests ────────────────────────────────────────


class TestContactSyncEventData:
    """Tests for contact.created / contact.updated payload."""

    def test_valid_payload_parses(self, contact_sync_data: dict[str, Any]) -> None:
        """Valid dict is accepted and all fields are accessible."""
        model = ContactSyncEventData.model_validate(contact_sync_data)
        assert model.integration_source == "google"
        assert model.external_id == "people/c123456789"
        assert model.contact_data == {"first_name": "Alice", "last_name": "Smith"}
        assert model.sync_type == "created"
        assert model.etag == "abc123"

    def test_roundtrip_serialization(self, contact_sync_data: dict[str, Any]) -> None:
        """model_validate → model_dump roundtrip preserves data."""
        model = ContactSyncEventData.model_validate(contact_sync_data)
        dumped = model.model_dump()
        restored = ContactSyncEventData.model_validate(dumped)
        assert restored == model

    def test_etag_optional(self, contact_sync_data: dict[str, Any]) -> None:
        """etag can be None."""
        contact_sync_data["etag"] = None
        model = ContactSyncEventData.model_validate(contact_sync_data)
        assert model.etag is None

    def test_missing_integration_source_rejected(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del contact_sync_data["integration_source"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "integration_source" in str(exc_info.value)

    def test_missing_external_id_rejected(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del contact_sync_data["external_id"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "external_id" in str(exc_info.value)

    def test_missing_contact_data_rejected(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del contact_sync_data["contact_data"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "contact_data" in str(exc_info.value)

    def test_missing_sync_timestamp_rejected(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del contact_sync_data["sync_timestamp"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "sync_timestamp" in str(exc_info.value)

    def test_missing_sync_type_rejected(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del contact_sync_data["sync_type"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "sync_type" in str(exc_info.value)

    def test_user_id_parses(self, contact_sync_data: dict[str, Any]) -> None:
        model = ContactSyncEventData.model_validate(contact_sync_data)
        assert model.user_id == "user-1"

    def test_missing_user_id_rejected(self, contact_sync_data: dict[str, Any]) -> None:
        """A synced contact must name its owner; the backend never guesses."""
        del contact_sync_data["user_id"]
        with pytest.raises(ValidationError) as exc_info:
            ContactSyncEventData.model_validate(contact_sync_data)
        assert "user_id" in str(exc_info.value)

    @pytest.mark.parametrize("blank", [None, ""])
    def test_blank_user_id_rejected(
        self, contact_sync_data: dict[str, Any], blank: str | None
    ) -> None:
        contact_sync_data["user_id"] = blank
        with pytest.raises(ValidationError):
            ContactSyncEventData.model_validate(contact_sync_data)


class TestCreateContactSyncEvent:
    """``OutboxEvent.create_contact_sync_event`` names the contact's owner."""

    def test_event_data_carries_user_id(self) -> None:
        event = OutboxEvent.create_contact_sync_event(
            contact_data={"first_name": "Alice"},
            integration_source="google",
            external_id="people/c1",
            user_id="user-1",
        )

        assert event.event_data["user_id"] == "user-1"


# ── SyncCompletedEventData Tests ──────────────────────────────────────


class TestSyncCompletedEventData:
    """Tests for sync.completed payload."""

    def test_valid_payload_parses(self, sync_completed_data: dict[str, Any]) -> None:
        """Valid dict is accepted."""
        model = SyncCompletedEventData.model_validate(sync_completed_data)
        assert model.integration_source == "google"
        assert model.google_account_email == "user@gmail.com"
        assert model.metrics["contacts_processed"] == 10

    def test_roundtrip_serialization(self, sync_completed_data: dict[str, Any]) -> None:
        """Roundtrip preserves data."""
        model = SyncCompletedEventData.model_validate(sync_completed_data)
        dumped = model.model_dump()
        restored = SyncCompletedEventData.model_validate(dumped)
        assert restored == model

    def test_missing_google_account_email_rejected(
        self, sync_completed_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del sync_completed_data["google_account_email"]
        with pytest.raises(ValidationError) as exc_info:
            SyncCompletedEventData.model_validate(sync_completed_data)
        assert "google_account_email" in str(exc_info.value)

    def test_missing_metrics_rejected(
        self, sync_completed_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del sync_completed_data["metrics"]
        with pytest.raises(ValidationError) as exc_info:
            SyncCompletedEventData.model_validate(sync_completed_data)
        assert "metrics" in str(exc_info.value)


# ── JournalSyncEventData Tests ────────────────────────────────────────


class TestJournalSyncEventData:
    """Tests for journal_event.* payload."""

    def test_valid_payload_parses(self, journal_sync_data: dict[str, Any]) -> None:
        """Valid dict is accepted and all fields are accessible."""
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.integration_source == "google"
        assert model.external_event_id == "google:evt-123"
        assert model.journal_data["user_id"] == "user-1"
        assert model.sync_action == "created"
        assert model.contact_relationships == []

    def test_roundtrip_serialization(self, journal_sync_data: dict[str, Any]) -> None:
        """Roundtrip preserves data."""
        model = JournalSyncEventData.model_validate(journal_sync_data)
        dumped = model.model_dump()
        restored = JournalSyncEventData.model_validate(dumped)
        assert restored == model

    def test_existing_journal_id_optional(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """existing_journal_id can be None."""
        journal_sync_data["existing_journal_id"] = None
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.existing_journal_id is None

    def test_existing_journal_id_with_value(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """existing_journal_id can have an int value."""
        journal_sync_data["existing_journal_id"] = 99
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.existing_journal_id == 99

    def test_contact_relationships_defaults_to_empty(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """contact_relationships defaults to [] when not present."""
        del journal_sync_data["contact_relationships"]
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.contact_relationships == []

    def test_contact_relationships_with_entries(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """contact_relationships can hold relationship dicts."""
        journal_sync_data["contact_relationships"] = [
            {"email": "bob@example.com", "relationship_type": "INVITEE"},
        ]
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert len(model.contact_relationships) == 1
        assert model.contact_relationships[0]["email"] == "bob@example.com"

    def test_missing_external_event_id_rejected(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_sync_data["external_event_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSyncEventData.model_validate(journal_sync_data)
        assert "external_event_id" in str(exc_info.value)

    def test_missing_calendar_id_rejected(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_sync_data["calendar_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSyncEventData.model_validate(journal_sync_data)
        assert "calendar_id" in str(exc_info.value)

    def test_missing_journal_data_rejected(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_sync_data["journal_data"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSyncEventData.model_validate(journal_sync_data)
        assert "journal_data" in str(exc_info.value)

    def test_missing_calendar_info_data_rejected(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_sync_data["calendar_info_data"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSyncEventData.model_validate(journal_sync_data)
        assert "calendar_info_data" in str(exc_info.value)

    def test_etag_optional(self, journal_sync_data: dict[str, Any]) -> None:
        """etag can be omitted."""
        del journal_sync_data["etag"]
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.etag is None


# ── MatchDetectionEventData Tests ─────────────────────────────────────


class TestMatchDetectionEventData:
    """Tests for journal_review.detect_matches payload."""

    def test_valid_payload_parses(self, match_detection_data: dict[str, Any]) -> None:
        """Valid dict is accepted."""
        model = MatchDetectionEventData.model_validate(match_detection_data)
        assert model.journal_id == 42
        assert model.user_id == "user-1"
        assert model.journal_title == "Team Standup"

    def test_roundtrip_serialization(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Roundtrip preserves data."""
        model = MatchDetectionEventData.model_validate(match_detection_data)
        dumped = model.model_dump()
        restored = MatchDetectionEventData.model_validate(dumped)
        assert restored == model

    def test_missing_journal_id_rejected(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del match_detection_data["journal_id"]
        with pytest.raises(ValidationError) as exc_info:
            MatchDetectionEventData.model_validate(match_detection_data)
        assert "journal_id" in str(exc_info.value)

    def test_missing_event_date_range_start_rejected(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del match_detection_data["event_date_range_start"]
        with pytest.raises(ValidationError) as exc_info:
            MatchDetectionEventData.model_validate(match_detection_data)
        assert "event_date_range_start" in str(exc_info.value)

    def test_journal_content_defaults_to_empty(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """journal_content defaults to '' when not present."""
        del match_detection_data["journal_content"]
        model = MatchDetectionEventData.model_validate(match_detection_data)
        assert model.journal_content == ""

    def test_invalid_datetime_rejected(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Non-ISO datetime string is rejected by AwareDatetime."""
        match_detection_data["event_date_range_start"] = "not-a-date"
        with pytest.raises(ValidationError) as exc_info:
            MatchDetectionEventData.model_validate(match_detection_data)
        assert "event_date_range_start" in str(exc_info.value)

    def test_naive_datetime_rejected(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Naive datetime (no timezone) is rejected by AwareDatetime."""
        match_detection_data["event_date_range_start"] = "2024-01-15T09:00:00"
        with pytest.raises(ValidationError) as exc_info:
            MatchDetectionEventData.model_validate(match_detection_data)
        assert "event_date_range_start" in str(exc_info.value)

    def test_parsed_datetime_is_aware(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """Parsed datetime fields are timezone-aware datetime objects."""
        model = MatchDetectionEventData.model_validate(match_detection_data)
        assert isinstance(model.event_date_range_start, datetime)
        assert model.event_date_range_start.tzinfo is not None
        assert isinstance(model.event_date_range_end, datetime)
        assert model.event_date_range_end.tzinfo is not None


# ── JournalStatusEventData Tests ──────────────────────────────────────


class TestJournalStatusEventData:
    """Tests for journal_event.conflicted / journal_event.cancelled payload."""

    def test_valid_payload_parses(self, journal_status_data: dict[str, Any]) -> None:
        """Valid dict is accepted and all fields are accessible."""
        model = JournalStatusEventData.model_validate(journal_status_data)
        assert model.external_event_id == "google:evt-456"
        assert model.calendar_id == "00000000-0000-0000-0000-000000000001"
        assert model.existing_journal_id == 10

    def test_existing_journal_id_optional(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """existing_journal_id can be None."""
        journal_status_data["existing_journal_id"] = None
        model = JournalStatusEventData.model_validate(journal_status_data)
        assert model.existing_journal_id is None

    def test_missing_external_event_id_rejected(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_status_data["external_event_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalStatusEventData.model_validate(journal_status_data)
        assert "external_event_id" in str(exc_info.value)

    def test_missing_calendar_id_rejected(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del journal_status_data["calendar_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalStatusEventData.model_validate(journal_status_data)
        assert "calendar_id" in str(exc_info.value)

    def test_accepts_full_journal_sync_payload(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Full JournalSyncEventData dict validates against the lightweight model.

        Publishers always send the full payload, so the status model must
        accept (and ignore) the extra fields.
        """
        model = JournalStatusEventData.model_validate(journal_sync_data)
        assert model.external_event_id == "google:evt-123"


# ── parse_outbox_event_data Tests ─────────────────────────────────────


class TestParseOutboxEventData:
    """Tests for the event_type → payload model dispatcher."""

    def test_contact_created_dispatches(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """contact.created dispatches to ContactSyncEventData."""
        result = parse_outbox_event_data("contact.created", contact_sync_data)
        assert isinstance(result, ContactSyncEventData)

    def test_contact_updated_dispatches(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """contact.updated dispatches to ContactSyncEventData."""
        result = parse_outbox_event_data("contact.updated", contact_sync_data)
        assert isinstance(result, ContactSyncEventData)

    def test_sync_completed_dispatches(
        self, sync_completed_data: dict[str, Any]
    ) -> None:
        """sync.completed dispatches to SyncCompletedEventData."""
        result = parse_outbox_event_data("sync.completed", sync_completed_data)
        assert isinstance(result, SyncCompletedEventData)

    def test_journal_event_created_dispatches(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """journal_event.created dispatches to JournalSyncEventData."""
        result = parse_outbox_event_data("journal_event.created", journal_sync_data)
        assert isinstance(result, JournalSyncEventData)

    def test_journal_event_updated_dispatches(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """journal_event.updated dispatches to JournalSyncEventData."""
        result = parse_outbox_event_data("journal_event.updated", journal_sync_data)
        assert isinstance(result, JournalSyncEventData)

    def test_journal_event_conflicted_dispatches(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """journal_event.conflicted dispatches to JournalStatusEventData."""
        result = parse_outbox_event_data(
            "journal_event.conflicted", journal_status_data
        )
        assert isinstance(result, JournalStatusEventData)

    def test_journal_event_cancelled_dispatches(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """journal_event.cancelled dispatches to JournalStatusEventData."""
        result = parse_outbox_event_data("journal_event.cancelled", journal_status_data)
        assert isinstance(result, JournalStatusEventData)

    def test_journal_review_detect_matches_dispatches(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """journal_review.detect_matches dispatches to MatchDetectionEventData."""
        result = parse_outbox_event_data(
            "journal_review.detect_matches", match_detection_data
        )
        assert isinstance(result, MatchDetectionEventData)

    def test_immich_album_created_dispatches(
        self, immich_album_data: dict[str, Any]
    ) -> None:
        """immich_album.created dispatches to ImmichAlbumSyncEventData."""
        result = parse_outbox_event_data("immich_album.created", immich_album_data)
        assert isinstance(result, ImmichAlbumSyncEventData)
        assert result.integration_source == "immich_album"

    def test_immich_album_updated_dispatches(
        self, immich_album_data: dict[str, Any]
    ) -> None:
        """immich_album.updated dispatches to ImmichAlbumSyncEventData."""
        result = parse_outbox_event_data("immich_album.updated", immich_album_data)
        assert isinstance(result, ImmichAlbumSyncEventData)

    def test_unknown_event_type_raises(self) -> None:
        """Unknown event type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown event type"):
            parse_outbox_event_data("unknown.event", {})

    def test_invalid_payload_raises_validation_error(self) -> None:
        """Invalid payload for known type raises ValidationError."""
        with pytest.raises(ValidationError):
            parse_outbox_event_data("contact.created", {"bad": "data"})


# ── OutboxEventData type alias Tests ──────────────────────────────────


class TestOutboxEventDataTypeAlias:
    """Tests for the union type alias."""

    def test_contact_sync_is_outbox_event_data(
        self, contact_sync_data: dict[str, Any]
    ) -> None:
        """ContactSyncEventData is a valid OutboxEventData type."""
        model = ContactSyncEventData.model_validate(contact_sync_data)
        # Type alias is a Union, so isinstance works for any member
        assert isinstance(model, ContactSyncEventData)
        # Ensure the type is within the union definition
        _: OutboxEventData = model  # noqa: F841 — type check only

    def test_match_detection_is_outbox_event_data(
        self, match_detection_data: dict[str, Any]
    ) -> None:
        """MatchDetectionEventData is a valid OutboxEventData type."""
        model = MatchDetectionEventData.model_validate(match_detection_data)
        _: OutboxEventData = model  # noqa: F841 — type check only


# ── Journal series payload Tests ──────────────────────────────────────


@pytest.fixture
def series_cancelled_data() -> dict[str, Any]:
    """Minimal valid JournalSeriesCancelledEventData payload."""
    return {
        "integration_source": "google",
        "calendar_id": "00000000-0000-0000-0000-000000000001",
        "recurring_event_id": "master123",
        "sync_timestamp": datetime.now(UTC).isoformat(),
    }


class TestJournalSyncEventDataRecurringEventId:
    """recurring_event_id on the full sync payload (series support)."""

    def test_defaults_to_none_for_old_payloads(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """Payloads emitted before the series feature still validate."""
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.recurring_event_id is None

    def test_accepts_recurring_event_id(
        self, journal_sync_data: dict[str, Any]
    ) -> None:
        """The recurring master event id round-trips."""
        journal_sync_data["recurring_event_id"] = "master123"
        model = JournalSyncEventData.model_validate(journal_sync_data)
        assert model.recurring_event_id == "master123"
        assert model.model_dump()["recurring_event_id"] == "master123"


class TestJournalStatusEventDataSeriesFields:
    """New optional fields on the lightweight status payload."""

    def test_new_fields_default_none_for_old_payloads(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """Payloads emitted before the series feature still validate."""
        model = JournalStatusEventData.model_validate(journal_status_data)
        assert model.recurring_event_id is None
        assert model.integration_source is None

    def test_accepts_recurring_event_id_and_source(
        self, journal_status_data: dict[str, Any]
    ) -> None:
        """recurring_event_id and integration_source are parsed when present."""
        journal_status_data["recurring_event_id"] = "master123"
        journal_status_data["integration_source"] = "google"
        model = JournalStatusEventData.model_validate(journal_status_data)
        assert model.recurring_event_id == "master123"
        assert model.integration_source == "google"


class TestJournalSeriesCancelledEventData:
    """Tests for journal_event.series_cancelled payload."""

    def test_valid_payload_parses(self, series_cancelled_data: dict[str, Any]) -> None:
        """Valid dict is accepted and all fields are accessible."""
        model = JournalSeriesCancelledEventData.model_validate(series_cancelled_data)
        assert model.integration_source == "google"
        assert model.calendar_id == "00000000-0000-0000-0000-000000000001"
        assert model.recurring_event_id == "master123"

    def test_missing_recurring_event_id_rejected(
        self, series_cancelled_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del series_cancelled_data["recurring_event_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSeriesCancelledEventData.model_validate(series_cancelled_data)
        assert "recurring_event_id" in str(exc_info.value)

    def test_missing_calendar_id_rejected(
        self, series_cancelled_data: dict[str, Any]
    ) -> None:
        """Missing required field raises ValidationError."""
        del series_cancelled_data["calendar_id"]
        with pytest.raises(ValidationError) as exc_info:
            JournalSeriesCancelledEventData.model_validate(series_cancelled_data)
        assert "calendar_id" in str(exc_info.value)

    def test_series_cancelled_dispatches_to_model(
        self, series_cancelled_data: dict[str, Any]
    ) -> None:
        """journal_event.series_cancelled dispatches to the new payload model."""
        parsed = parse_outbox_event_data(
            "journal_event.series_cancelled", series_cancelled_data
        )
        assert isinstance(parsed, JournalSeriesCancelledEventData)


@pytest.fixture
def duration_corrected_data() -> dict[str, Any]:
    """Minimal valid FitnessDurationCorrectedData payload."""
    return {
        "journal_id": 42,
        "user_id": "user-1",
        "expected_durations": [3000],
        "corrected_duration": 3600,
        "strava_activity_ids": ["123"],
    }


class TestFitnessDurationCorrectedData:
    """Tests for journal_event.fitness_duration_corrected payload."""

    def test_valid_payload_parses(
        self, duration_corrected_data: dict[str, Any]
    ) -> None:
        model = FitnessDurationCorrectedData.model_validate(duration_corrected_data)
        assert model.journal_id == 42
        assert model.user_id == "user-1"
        assert model.expected_durations == [3000]
        assert model.corrected_duration == 3600
        assert model.strava_activity_ids == ["123"]

    def test_empty_expected_durations_rejected(
        self, duration_corrected_data: dict[str, Any]
    ) -> None:
        """With nothing to compare against, the correction could never apply."""
        duration_corrected_data["expected_durations"] = []
        with pytest.raises(ValidationError) as exc_info:
            FitnessDurationCorrectedData.model_validate(duration_corrected_data)
        assert "expected_durations" in str(exc_info.value)

    @pytest.mark.parametrize("field", ["corrected_duration", "expected_durations"])
    def test_negative_duration_rejected(
        self, duration_corrected_data: dict[str, Any], field: str
    ) -> None:
        duration_corrected_data[field] = [-1] if field == "expected_durations" else -1
        with pytest.raises(ValidationError) as exc_info:
            FitnessDurationCorrectedData.model_validate(duration_corrected_data)
        assert field in str(exc_info.value)

    def test_blank_user_id_rejected(
        self, duration_corrected_data: dict[str, Any]
    ) -> None:
        duration_corrected_data["user_id"] = ""
        with pytest.raises(ValidationError) as exc_info:
            FitnessDurationCorrectedData.model_validate(duration_corrected_data)
        assert "user_id" in str(exc_info.value)

    def test_dispatches_to_model(self, duration_corrected_data: dict[str, Any]) -> None:
        parsed = parse_outbox_event_data(
            "journal_event.fitness_duration_corrected", duration_corrected_data
        )
        assert isinstance(parsed, FitnessDurationCorrectedData)


class TestCreateFitnessDurationCorrectionEvent:
    """Tests for OutboxEvent.create_fitness_duration_correction_event."""

    def test_builds_event_keyed_on_the_journal(self) -> None:
        event = OutboxEvent.create_fitness_duration_correction_event(
            journal_id=42,
            user_id="user-1",
            expected_durations=[3000, 3300],
            corrected_duration=3600,
            strava_activity_ids=["123", "456"],
        )

        assert event.event_type == "journal_event.fitness_duration_corrected"
        assert event.aggregate_id == 42
        assert event.event_data == {
            "journal_id": 42,
            "user_id": "user-1",
            "expected_durations": [3000, 3300],
            "corrected_duration": 3600,
            "strava_activity_ids": ["123", "456"],
        }
