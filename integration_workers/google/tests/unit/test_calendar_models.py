from typing import Any

import pytest
from pydantic import ValidationError

from calendar_models import GoogleCalendar, GoogleEvent, GoogleEventStartEnd

def test_google_calendar_parsing() -> None:
    raw_api_response: dict[str, Any] = {
        "kind": "calendar#calendarListEntry",
        "etag": '"1234567890"',
        "id": "user@example.com",
        "summary": "Primary Calendar",
        "description": "My main calendar",
        "timeZone": "UTC",
        "colorId": "14",
        "backgroundColor": "#9fe1e7",
        "foregroundColor": "#000000",
        "selected": True,
        "accessRole": "owner",
        "primary": True
    }

    calendar = GoogleCalendar(
        id=raw_api_response["id"],
        summary=raw_api_response["summary"],
        description=raw_api_response.get("description"),
        primary=raw_api_response.get("primary", False),
        access_role=raw_api_response.get("accessRole")
    )

    assert calendar.id == "user@example.com"
    assert calendar.summary == "Primary Calendar"
    assert calendar.description == "My main calendar"
    assert calendar.primary is True
    assert calendar.access_role == "owner"


def test_google_event_parsing() -> None:
    raw_api_response: dict[str, Any] = {
        "kind": "calendar#event",
        "etag": '"123456"',
        "id": "event_123",
        "status": "confirmed",
        "htmlLink": "https://www.google.com/calendar/event?eid=123",
        "created": "2024-01-01T00:00:00.000Z",
        "updated": "2024-01-02T00:00:00.000Z",
        "summary": "Meeting with team",
        "description": "Discuss project status",
        "location": "Conference Room A",
        "start": {
            "dateTime": "2024-01-10T10:00:00Z",
            "timeZone": "UTC"
        },
        "end": {
            "dateTime": "2024-01-10T11:00:00Z",
            "timeZone": "UTC"
        }
    }

    start_data = raw_api_response.get("start", {})
    end_data = raw_api_response.get("end", {})

    event = GoogleEvent(
        id=raw_api_response["id"],
        status=raw_api_response.get("status"),
        htmlLink=raw_api_response.get("htmlLink"),
        created=raw_api_response.get("created"),
        updated=raw_api_response.get("updated"),
        summary=raw_api_response.get("summary"),
        description=raw_api_response.get("description"),
        location=raw_api_response.get("location"),
        start=GoogleEventStartEnd(**start_data) if start_data else None,
        end=GoogleEventStartEnd(**end_data) if end_data else None,
        etag=raw_api_response.get("etag")
    )

    assert event.id == "event_123"
    assert event.summary == "Meeting with team"
    assert event.start is not None
    assert event.start.date_time == "2024-01-10T10:00:00Z"
    assert event.end is not None
    assert event.end.date_time == "2024-01-10T11:00:00Z"
    assert event.html_link == "https://www.google.com/calendar/event?eid=123"


def test_google_event_all_day_parsing() -> None:
    raw_api_response: dict[str, Any] = {
        "id": "event_456",
        "summary": "Holiday",
        "start": {
            "date": "2024-12-25"
        },
        "end": {
            "date": "2024-12-26"
        }
    }

    start_data = raw_api_response.get("start", {})
    end_data = raw_api_response.get("end", {})

    event = GoogleEvent(
        id=raw_api_response["id"],
        summary=raw_api_response.get("summary"),
        start=GoogleEventStartEnd(**start_data) if start_data else None,
        end=GoogleEventStartEnd(**end_data) if end_data else None,
    )

    assert event.id == "event_456"
    assert event.start is not None
    assert event.start.date == "2024-12-25"
    assert event.start.date_time is None
