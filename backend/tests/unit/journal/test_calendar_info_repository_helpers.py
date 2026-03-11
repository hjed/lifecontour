"""Unit tests for calendar info repository compatibility helpers."""

from datetime import UTC, datetime, time
from uuid import uuid4

import pytest

from app.core.journal.adapters.sql.calendar_info_repository import (
    project_calendar_info_to_linked_calendar,
)
from app.core.journal.models.calendar_info import CalendarInfo


@pytest.mark.unit
class TestProjectCalendarInfoToLinkedCalendar:
    """Test compatibility projection for linked calendars."""

    def test_projects_legacy_calendar_info_to_requested_link(self) -> None:
        """Projecting a legacy event to a linked calendar should preserve event data."""
        original_calendar_id = uuid4()
        linked_calendar_id = uuid4()
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)
        calendar_info = CalendarInfo(
            journal_id=42,
            calendar_id=original_calendar_id,
            start_time=time(9, 0),
            end_time=time(10, 0),
            location="Conference Room A",
            sync_invitees=True,
            created_at=created_at,
            updated_at=updated_at,
        )

        projected = project_calendar_info_to_linked_calendar(
            calendar_info,
            linked_calendar_id,
        )

        assert projected is not calendar_info
        assert projected.journal_id == calendar_info.journal_id
        assert projected.calendar_id == linked_calendar_id
        assert projected.start_time == calendar_info.start_time
        assert projected.end_time == calendar_info.end_time
        assert projected.location == calendar_info.location
        assert projected.sync_invitees is True
        assert projected.created_at == created_at
        assert projected.updated_at == updated_at
        assert calendar_info.calendar_id == original_calendar_id
