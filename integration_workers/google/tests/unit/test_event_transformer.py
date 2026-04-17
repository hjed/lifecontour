import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from core_shared.models.journals import CalendarInfo, EventDateRange, Journal

from calendar_models import GoogleEvent
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
        result = transformer.transform_event(google_event, user_id, calendar_id)
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
        assert calendar_info.start_time == expected_start_dt.time().replace(tzinfo=None)
        assert calendar_info.end_time == expected_end_dt.time().replace(tzinfo=None)
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
        result = transformer.transform_event(google_event, user_id, calendar_id)
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
            "id": "event789",
            "summary": "Cancelled Meeting",
            "status": "cancelled",
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
            "id": "event_zulu",
            "summary": "Zulu Meeting",
            "start": {"dateTime": "2023-10-27T10:00:00Z"},
            "end": {"dateTime": "2023-10-27T11:00:00Z"},
            "status": "confirmed",
        }
        google_event = GoogleEvent.model_validate(google_event_dict)
        transformer = GoogleEventTransformer()
        user_id = "user_123"
        calendar_id = uuid.uuid4()

        # Act
        result = transformer.transform_event(google_event, user_id, calendar_id)
        assert result is not None
        journal, _ = result

        # Assert
        assert journal.event_date_range is not None
        assert (
            journal.event_date_range.start.isoformat(timespec="seconds")
            == "2023-10-27T10:00:00+00:00"
        )

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
            start_time=start_dt.time().replace(tzinfo=None),
            end_time=end_dt.time().replace(tzinfo=None),
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

    def test_transform_to_google_event_payload_includes_invitees_if_sync_enabled(
        self,
    ) -> None:
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
            start_time=start_dt.time().replace(tzinfo=None),
            end_time=end_dt.time().replace(tzinfo=None),
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

    def test_transform_to_google_event_payload_omits_invitees_if_sync_disabled(
        self,
    ) -> None:
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
            start_time=start_dt.time().replace(tzinfo=None),
            end_time=end_dt.time().replace(tzinfo=None),
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
        result = transformer.transform_event(google_event, user_id, calendar_id)
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


class TestGoogleEventTransformerEventState:
    """Tests for Google event status → EventState mapping."""

    def test_confirmed_event_maps_to_confirmed(self) -> None:
        """Event with status='confirmed' should have event_state=CONFIRMED."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_confirmed",
                "summary": "Confirmed Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.CONFIRMED

    def test_null_status_maps_to_confirmed(self) -> None:
        """Event with no status should default to CONFIRMED."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_no_status",
                "summary": "No Status Event",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.CONFIRMED

    def test_tentative_status_maps_to_tentative(self) -> None:
        """Event with status='tentative' should have event_state=TENTATIVE."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_tentative",
                "summary": "Tentative Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "tentative",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.TENTATIVE

    def test_self_attendee_needs_action_maps_to_invited(self) -> None:
        """Self-attendee with responseStatus='needsAction' → INVITED."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_invite",
                "summary": "Party Invite",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "user@example.com", "responseStatus": "needsAction"},
                    {"email": "other@example.com", "responseStatus": "accepted"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(
            google_event,
            "user1",
            uuid.uuid4(),
            self_email="user@example.com",
        )
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.INVITED

    def test_self_attendee_tentative_maps_to_tentative(self) -> None:
        """Self-attendee with responseStatus='tentative' ("maybe") → TENTATIVE."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_maybe",
                "summary": "Maybe Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "user@example.com", "responseStatus": "tentative"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(
            google_event,
            "user1",
            uuid.uuid4(),
            self_email="user@example.com",
        )
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.TENTATIVE

    def test_self_attendee_accepted_stays_confirmed(self) -> None:
        """Self-attendee with responseStatus='accepted' → CONFIRMED."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_accepted",
                "summary": "Accepted Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "user@example.com", "responseStatus": "accepted"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(
            google_event,
            "user1",
            uuid.uuid4(),
            self_email="user@example.com",
        )
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.CONFIRMED

    def test_no_self_email_no_attendee_override(self) -> None:
        """Without self_email, attendee responseStatus is not considered."""
        from core_shared.models.journals.event_state import EventState

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_no_self",
                "summary": "Meeting No Self",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "user@example.com", "responseStatus": "needsAction"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.event_state == EventState.CONFIRMED


class TestGoogleEventTransformerMultiDayEvents:
    """Tests for multi-day timed events that span midnight."""

    def test_multi_day_timed_event_preserves_times_with_date_context(self) -> None:
        """Multi-day timed events should preserve times.

        When a timed event spans multiple days (e.g. 23:00 to 01:00 next day),
        CalendarInfo receives event dates for date-aware validation, allowing
        start_time > end_time when the event spans midnight.
        """
        google_event = GoogleEvent.model_validate(
            {
                "id": "multi_day_timed",
                "summary": "Overnight Event",
                "start": {"dateTime": "2023-10-27T23:00:00Z"},
                "end": {"dateTime": "2023-10-28T01:00:00Z"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        journal, calendar_info = result

        # Full datetime precision preserved in EventDateRange
        expected_start = datetime(2023, 10, 27, 23, 0, tzinfo=UTC)
        expected_end = datetime(2023, 10, 28, 1, 0, tzinfo=UTC)
        assert journal.event_date_range == EventDateRange(
            start=expected_start, end=expected_end
        )

        # Times are preserved (not nulled) for multi-day timed events
        from datetime import date, time

        assert calendar_info.start_time == time(23, 0)
        assert calendar_info.end_time == time(1, 0)
        assert calendar_info.is_all_day is False
        assert calendar_info.event_start_date == date(2023, 10, 27)
        assert calendar_info.event_end_date == date(2023, 10, 28)

    def test_multi_day_timed_event_spanning_several_days(self) -> None:
        """Multi-day timed event spanning several days preserves times."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "multi_day_long",
                "summary": "Conference",
                "start": {"dateTime": "2023-10-27T09:00:00Z"},
                "end": {"dateTime": "2023-10-29T17:00:00Z"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        journal, calendar_info = result

        expected_start = datetime(2023, 10, 27, 9, 0, tzinfo=UTC)
        expected_end = datetime(2023, 10, 29, 17, 0, tzinfo=UTC)
        assert journal.event_date_range == EventDateRange(
            start=expected_start, end=expected_end
        )

        from datetime import time

        assert calendar_info.start_time == time(9, 0)
        assert calendar_info.end_time == time(17, 0)
        assert calendar_info.is_all_day is False

    def test_same_day_event_still_has_times(self) -> None:
        """Same-day timed events should still have CalendarInfo times."""
        from datetime import time

        google_event = GoogleEvent.model_validate(
            {
                "id": "same_day",
                "summary": "Quick Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result

        assert calendar_info.start_time == time(10, 0)
        assert calendar_info.end_time == time(11, 0)
        assert calendar_info.is_all_day is False


class TestGoogleEventTransformerTimezone:
    """Tests for timezone extraction and preservation in Google event sync."""

    def test_inbound_event_extracts_start_timezone(self) -> None:
        """Timezone from start.timeZone is extracted into CalendarInfo and correctly transforms UTC times to local Wall Clock times."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_1",
                "summary": "Sydney Meeting",
                "start": {
                    "dateTime": "2023-10-27T10:00:00+11:00",
                    "timeZone": "Australia/Sydney",
                },
                "end": {
                    "dateTime": "2023-10-27T11:00:00+11:00",
                    "timeZone": "Australia/Sydney",
                },
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result

        assert calendar_info.timezone == "Australia/Sydney"

        # Verify local date was correctly offset from UTC date (which was 26 Oct 23:00)
        assert calendar_info.event_start_date == date(2023, 10, 27)
        assert calendar_info.event_end_date == date(2023, 10, 27)

        # Verify local time was correctly translated from UTC
        assert calendar_info.start_time == time(10, 0)
        assert calendar_info.end_time == time(11, 0)

    def test_inbound_event_no_timezone_returns_none(self) -> None:
        """When no timeZone is set on start/end, CalendarInfo.timezone is None."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_2",
                "summary": "UTC Meeting",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.timezone is None

    def test_inbound_all_day_event_no_timezone(self) -> None:
        """All-day events should not have a timezone even if set on the event."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_allday",
                "summary": "Holiday",
                "start": {"date": "2023-12-25"},
                "end": {"date": "2023-12-26"},
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.timezone is None

    def test_inbound_all_day_event_ignores_timezone_when_present(self) -> None:
        """All-day events ignore start/end timeZone values when date is used."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_allday_with_timezone",
                "summary": "Holiday",
                "start": {
                    "date": "2023-12-25",
                    "timeZone": "America/New_York",
                },
                "end": {
                    "date": "2023-12-26",
                    "timeZone": "America/New_York",
                },
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.timezone is None

    def test_outbound_payload_includes_timezone_when_set(self) -> None:
        """Outbound Google payload includes timeZone on start/end when set."""
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Sydney Meeting",
            content="",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=start_dt.time().replace(tzinfo=None),
            end_time=end_dt.time().replace(tzinfo=None),
            is_all_day=False,
            timezone="Australia/Sydney",
        )

        payload = transformer.transform_to_google_event_payload(journal, calendar_info)
        assert payload["start"]["timeZone"] == "Australia/Sydney"
        assert payload["end"]["timeZone"] == "Australia/Sydney"

    def test_outbound_payload_omits_timezone_when_none(self) -> None:
        """Outbound Google payload omits timeZone when CalendarInfo.timezone is None."""
        transformer = GoogleEventTransformer()
        start_dt = datetime(2023, 10, 27, 10, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 27, 11, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="UTC Meeting",
            content="",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=start_dt.time().replace(tzinfo=None),
            end_time=end_dt.time().replace(tzinfo=None),
            is_all_day=False,
            timezone=None,
        )

        payload = transformer.transform_to_google_event_payload(journal, calendar_info)
        assert "timeZone" not in payload["start"]
        assert "timeZone" not in payload["end"]

    def test_outbound_payload_translates_local_time_to_utc_with_midnight_crossing(
        self,
    ) -> None:
        """Outbound Google payload maps a local start_time that crosses UTC midnight back into the correct UTC offset string."""
        transformer = GoogleEventTransformer()

        # Scenario: Sydney 10:00 AM Thursday, which is UTC 23:00 Wednesday.
        # This crosses the UTC midnight boundary backwards.
        start_dt = datetime(2023, 10, 25, 23, 0, tzinfo=UTC)
        end_dt = datetime(2023, 10, 26, 0, 0, tzinfo=UTC)

        journal = Journal(
            user_id="user_123",
            title="Sydney Morning Meeting",
            content="",
            event_date_range=EventDateRange(start=start_dt, end=end_dt),
        )

        # The local times that we expect the UI / Database to be storing
        calendar_info = CalendarInfo(
            calendar_id=uuid.uuid4(),
            start_time=time(10, 0),
            end_time=time(11, 0),
            is_all_day=False,
            timezone="Australia/Sydney",
            event_start_date=date(2023, 10, 26),
            event_end_date=date(2023, 10, 26),
        )

        payload = transformer.transform_to_google_event_payload(journal, calendar_info)

        # It should reconstruct back to the proper UTC string matching our start_dt and end_dt
        assert payload["start"]["dateTime"] == "2023-10-25T23:00:00Z"
        assert payload["end"]["dateTime"] == "2023-10-26T00:00:00Z"
        assert payload["start"]["timeZone"] == "Australia/Sydney"
        assert payload["end"]["timeZone"] == "Australia/Sydney"

    def test_inbound_event_prefers_start_timezone(self) -> None:
        """When start and end have different timezones, start is preferred."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_diff",
                "summary": "Cross TZ Meeting",
                "start": {
                    "dateTime": "2023-10-27T10:00:00+11:00",
                    "timeZone": "Australia/Sydney",
                },
                "end": {
                    "dateTime": "2023-10-27T11:00:00+05:30",
                    "timeZone": "Asia/Kolkata",
                },
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.timezone == "Australia/Sydney"

    def test_inbound_event_falls_back_to_end_timezone(self) -> None:
        """When only end has a timezone, it is used as fallback."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "tz_event_end_only",
                "summary": "End TZ Only",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {
                    "dateTime": "2023-10-27T18:00:00+05:30",
                    "timeZone": "Asia/Kolkata",
                },
                "status": "confirmed",
            }
        )
        transformer = GoogleEventTransformer()
        result = transformer.transform_event(google_event, "user1", uuid.uuid4())
        assert result is not None
        _, calendar_info = result
        assert calendar_info.timezone == "Asia/Kolkata"


class TestGoogleEventTransformerContactRelationships:
    """Tests for extracting contact relationships from Google events."""

    def test_extract_contact_relationships_maps_status(self) -> None:
        """Test that responseStatus maps to the correct AttendeeStatus."""
        from core_shared.models.journals.attendee_status import AttendeeStatus

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_status",
                "summary": "Status mapping",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "accepted@example.com", "responseStatus": "accepted"},
                    {"email": "needs@example.com", "responseStatus": "needsAction"},
                    {"email": "tentative@example.com", "responseStatus": "tentative"},
                    {"email": "declined@example.com", "responseStatus": "declined"},
                    {"email": "none@example.com"},  # Assuming no status maps to NO_REPLY
                ],
            }
        )
        transformer = GoogleEventTransformer()
        rels = transformer.extract_contact_relationships(google_event)

        rel_by_email = {r["email"]: r for r in rels}

        assert rel_by_email["accepted@example.com"]["status"] == AttendeeStatus.ATTENDING.value
        assert rel_by_email["needs@example.com"]["status"] == AttendeeStatus.NO_REPLY.value
        assert rel_by_email["tentative@example.com"]["status"] == AttendeeStatus.MAYBE.value
        assert rel_by_email["declined@example.com"]["status"] == AttendeeStatus.DECLINED.value
        assert rel_by_email["none@example.com"]["status"] == AttendeeStatus.NO_REPLY.value

    def test_extract_contact_relationships_maps_organizer(self) -> None:
        """Test that organizer: true maps to ContactEventRole.ORGANISER."""
        from core_shared.models.journals.contact_event_role import ContactEventRole

        google_event = GoogleEvent.model_validate(
            {
                "id": "event_org",
                "summary": "Org mapping",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "org@example.com", "responseStatus": "accepted", "organizer": True},
                    {"email": "guest@example.com", "responseStatus": "needsAction"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        rels = transformer.extract_contact_relationships(google_event)

        rel_by_email = {r["email"]: r for r in rels}

        assert rel_by_email["org@example.com"]["role"] == ContactEventRole.ORGANISER.value
        assert "role" not in rel_by_email["guest@example.com"]

    def test_extract_contact_relationships_skips_empty_emails(self) -> None:
        """Test that attendees without an email are skipped."""
        google_event = GoogleEvent.model_validate(
            {
                "id": "event_empty",
                "summary": "Empty email",
                "start": {"dateTime": "2023-10-27T10:00:00Z"},
                "end": {"dateTime": "2023-10-27T11:00:00Z"},
                "status": "confirmed",
                "attendees": [
                    {"email": "", "responseStatus": "accepted"},
                    {"email": "valid@example.com", "responseStatus": "accepted"},
                ],
            }
        )
        transformer = GoogleEventTransformer()
        rels = transformer.extract_contact_relationships(google_event)

        assert len(rels) == 1
        assert rels[0]["email"] == "valid@example.com"

