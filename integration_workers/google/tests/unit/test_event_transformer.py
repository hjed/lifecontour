import uuid
from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import CalendarInfo, EventDateRange, Journal

from calendar_models import GoogleEvent

# We will import the GoogleEventTransformer once we implement it.
from event_transformer import GoogleEventTransformer


class TestGoogleEventTransformer:
    def test_transform_event_maps_basic_fields_correctly(self) -> None:
        # Arrange
        google_event_dict = {
            "id": "event123",
            "summary": "Team Meeting",
            "description": "Discuss project status",
            "location": "Conference Room A",
            "start": {"dateTime": "2023-10-27T10:00:00Z"},
            "end": {"dateTime": "2023-10-27T11:00:00Z"},
            "status": "confirmed",
        }
        google_event = GoogleEvent.model_validate(google_event_dict)
        transformer = GoogleEventTransformer()
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act
        result = transformer.transform_event(
            google_event, user_id, calendar_id
        )
        assert result is not None
        journal, calendar_info = result

        # Assert
        assert journal.title == "Team Meeting"
        assert journal.content == "Discuss project status"
        assert journal.user_id == user_id

        # Date range on Journal
        expected_start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        expected_end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)
        assert journal.event_date_range == EventDateRange(
            start=expected_start_dt, end=expected_end_dt
        )

        # CalendarInfo properties
        assert calendar_info.location == "Conference Room A"
        assert calendar_info.is_all_day is False
        assert calendar_info.start_time == expected_start_dt.time()
        assert calendar_info.end_time == expected_end_dt.time()
        assert (
            calendar_info.calendar_id is not None
        )  # Usually gets populated later or requires a calendar ID

    def test_transform_event_handles_all_day_events(self) -> None:
        # Arrange
        google_event_dict = {
            "id": "event456",
            "summary": "Company Holiday",
            "start": {"date": "2023-12-25"},
            "end": {"date": "2023-12-26"},
            "status": "confirmed",
        }
        google_event = GoogleEvent.model_validate(google_event_dict)
        transformer = GoogleEventTransformer()
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act
        result = transformer.transform_event(
            google_event, user_id, calendar_id
        )
        assert result is not None
        journal, calendar_info = result

        # Assert
        assert journal.title == "Company Holiday"
        assert calendar_info.is_all_day is True

        # All-day events in Google Calendar have 'date' fields.
        # When mapped to our backend, they should be mapped to the start of the day in UTC for EventDateRange.
        expected_start_dt = datetime(2023, 12, 25, tzinfo=UTC)
        expected_end_dt = datetime(2023, 12, 25, tzinfo=UTC)

        assert journal.event_date_range == EventDateRange(
            start=expected_start_dt, end=expected_end_dt
        )

        # Time aspects of CalendarInfo should be None for all-day events
        assert calendar_info.start_time is None
        assert calendar_info.end_time is None

    def test_transform_event_returns_none_for_cancelled_events(self) -> None:
        # Arrange
        google_event_dict: dict[str, Any] = {
            "id": "event789", "summary": "Cancelled Meeting", "status": "cancelled"
        }
        google_event = GoogleEvent.model_validate(google_event_dict)
        transformer = GoogleEventTransformer()
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act & Assert
        assert transformer.transform_event(google_event, user_id, calendar_id) is None

    def test_transform_event_handles_zulu_time(self) -> None:
        # Arrange
        google_event_dict: dict[str, Any] = {
            "id": "event_zulu", "summary": "Zulu Meeting",
            "start": {"dateTime": "2023-10-27T10:00:00Z"},
            "end": {"dateTime": "2023-10-27T11:00:00Z"},
            "status": "confirmed"
        }
        google_event = GoogleEvent.model_validate(google_event_dict)
        transformer = GoogleEventTransformer()
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act
        result = transformer.transform_event(google_event, user_id, calendar_id)
        assert result is not None
        journal, calendar_info = result

        # Assert
        assert journal.event_date_range is not None
        assert journal.event_date_range.start.isoformat(timespec="seconds") == "2023-10-27T10:00:00+00:00"

    def test_transform_to_google_event_payload_maps_timed_events(self) -> None:
        # Arrange
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Outbound Meeting",
            content="Syncing this out",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            is_all_day=False,
            location="Room 404",
        )

        # Act
        payload = transformer.transform_to_google_event_payload(journal, calendar_info)

        # Assert
        assert payload["summary"] == "Outbound Meeting"
        assert payload["description"] == "Syncing this out"
        assert payload["location"] == "Room 404"
        assert payload["start"]["dateTime"] == "2023-10-27T10:00:00Z"
        assert payload["end"]["dateTime"] == "2023-10-27T11:00:00Z"
        assert "date" not in payload["start"]
        assert "date" not in payload["end"]

    def test_transform_to_google_event_payload_maps_all_day_events(self) -> None:
        # Arrange
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 12, 25, tzinfo=UTC)
        end_dt = datetime(2023, 12, 26, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Christmas",
            content="Holiday",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(), is_all_day=True, location=None
        )

        # Act
        payload = transformer.transform_to_google_event_payload(journal, calendar_info)

        # Assert
        assert payload["summary"] == "Christmas"
        assert payload["description"] == "Holiday"
        assert "location" not in payload  # Should be excluded if None
        assert payload["start"]["date"] == "2023-12-25"
        assert payload["end"]["date"] == "2023-12-27"
        assert "dateTime" not in payload["start"]
        assert "dateTime" not in payload["end"]

    def test_transform_to_google_event_payload_includes_invitees_if_sync_enabled(self) -> None:
        # Arrange
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Meeting with Client",
            content="Important",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            is_all_day=False,
            sync_invitees=True,
        )
        invitees = ["client@example.com", "manager@example.com"]

        # Act
        payload = transformer.transform_to_google_event_payload(
            journal, calendar_info, invitee_emails=invitees
        )

        # Assert
        assert "attendees" in payload
        assert len(payload["attendees"]) == 2
        assert payload["attendees"][0]["email"] == "client@example.com"
        assert payload["attendees"][1]["email"] == "manager@example.com"

    def test_transform_to_google_event_payload_omits_invitees_if_sync_disabled(self) -> None:
        # Arrange
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Internal Prep",
            content="Prep for meeting",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=start_dt.time(),
            end_time=end_dt.time(),
            is_all_day=False,
            sync_invitees=False,
        )
        invitees = [
            "colleague@example.com"
        ]  # We have participants, but sync is disabled

        # Act
        payload = transformer.transform_to_google_event_payload(
            journal, calendar_info, invitee_emails=invitees
        )

        # Assert
        assert "attendees" not in payload

    def test_round_trip_transformation_timed_event(self) -> None:
        # Arrange
        transformer = GoogleEventTransformer()
        original_payload: dict[str, Any] = {
            "id": "event999",
            "summary": "Roundtrip Sync",
            "description": "Ensure we don't lose data",
            "location": "Boardroom",
            "start": {"dateTime": "2023-10-27T10:00:00Z"},
            "end": {"dateTime": "2023-10-27T11:00:00Z"},
            "status": "confirmed",
        }
        google_event = GoogleEvent.model_validate(original_payload)
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act 1: API to Domain
        result = transformer.transform_event(
            google_event, user_id, calendar_id
        )
        assert result is not None
        journal, calendar_info = result

        # Act 2: Domain to API payload
        new_payload = transformer.transform_to_google_event_payload(
            journal, calendar_info
        )

        # Assert consistency
        assert new_payload["summary"] == original_payload["summary"]
        assert new_payload["description"] == original_payload["description"]
        assert new_payload["location"] == original_payload["location"]
        assert new_payload["start"]["dateTime"] == original_payload["start"]["dateTime"]
        assert new_payload["end"]["dateTime"] == original_payload["end"]["dateTime"]
