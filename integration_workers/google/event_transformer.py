import uuid
from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import (
    CalendarInfo,
    EventDateRange,
    Journal,
    JournalValidationError,
)

from calendar_models import GoogleEvent, GoogleEventStartEnd

UTC_OFFSET_SUFFIX = "+00:00"


class GoogleEventTransformer:
    """Transforms events between Google Calendar API and internal Journal formats."""

    def transform_event(
        self, google_event: GoogleEvent, user_id: str, calendar_id: uuid.UUID
    ) -> tuple[Journal, CalendarInfo] | None:
        """
        Transform a GoogleEvent into a Journal and CalendarInfo tuple.

        Returns None if the event is cancelled or should not be synced.
        """
        if google_event.status == "cancelled":
            return None

        # Parse start dates
        start_dt, start_is_all_day = self._parse_event_time(google_event.start)
        end_dt, end_is_all_day = self._parse_event_time(google_event.end)

        # If the event doesn't specify end time, make it equal to start time
        if not end_dt:
            end_dt = start_dt

        # Fallbacks for mandatory data
        if not start_dt or not end_dt:
            # We can't sync an event without a start and end time
            return None

        assert end_dt is not None

        is_all_day = start_is_all_day or end_is_all_day

        from datetime import timedelta

        if is_all_day and end_is_all_day and end_dt > start_dt:
            end_dt = end_dt - timedelta(days=1)

        # Validate that end_dt >= start_dt to avoid JournalValidationError
        if end_dt < start_dt:
            return None

        date_range = EventDateRange(start=start_dt, end=end_dt)

        summary = (google_event.summary or "").strip() or "Untitled Event"
        description = (google_event.description or "").strip()

        try:
            journal = Journal(
                user_id=user_id,
                title=summary,
                content=description,
                event_date_range=date_range,
            )
        except JournalValidationError:
            return None

        if is_all_day:
            start_time = None
            end_time = None
        else:
            start_time = start_dt.time().replace(tzinfo=None)
            end_time = end_dt.time().replace(tzinfo=None)

        calendar_info = CalendarInfo(
            journal_id=None,
            calendar_id=calendar_id,
            start_time=start_time,
            end_time=end_time,
            is_all_day=is_all_day,
            location=google_event.location,
        )

        return journal, calendar_info

    def _parse_event_time(
        self, time_data: GoogleEventStartEnd | None
    ) -> tuple[datetime | None, bool]:
        """
        Parse GoogleEventStartEnd into UTC datetime and a boolean flag for all-day.
        """
        if not time_data:
            return None, False

        if time_data.date:
            return self._parse_all_day_date(time_data.date)
        elif time_data.date_time:
            return self._parse_timed_datetime(time_data.date_time, time_data.time_zone)

        return None, False

    def _parse_all_day_date(self, date_str: str) -> tuple[datetime | None, bool]:
        try:
            dt_naive = datetime.strptime(date_str, "%Y-%m-%d")
            dt_utc = dt_naive.replace(tzinfo=UTC)
            return dt_utc, True
        except ValueError:
            return None, False

    def _parse_timed_datetime(
        self, date_time_str: str, time_zone_str: str | None
    ) -> tuple[datetime | None, bool]:
        try:
            if date_time_str.endswith("Z"):
                date_time_str = date_time_str[:-1] + UTC_OFFSET_SUFFIX
            dt = datetime.fromisoformat(date_time_str)
            if dt.tzinfo is None:
                if time_zone_str:
                    try:
                        from zoneinfo import ZoneInfo

                        tz = ZoneInfo(time_zone_str)
                        dt = dt.replace(tzinfo=tz)
                    except Exception:
                        dt = dt.replace(tzinfo=UTC)
                else:
                    dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC), False
        except ValueError:
            return None, False

    def transform_to_google_event_payload(
        self,
        journal: Journal,
        calendar_info: CalendarInfo,
        invitee_emails: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Transform a Journal and CalendarInfo into a Google Calendar API event payload dictionary.
        This formats the payload for an insert or update request.
        """
        payload: dict[str, Any] = {
            "summary": journal.title,
            "description": journal.content,
        }

        if calendar_info.location:
            payload["location"] = calendar_info.location

        start_dt = journal.event_date_range.start
        end_dt = journal.event_date_range.end

        if calendar_info.is_all_day:
            from datetime import timedelta

            payload["start"] = {"date": start_dt.strftime("%Y-%m-%d")}
            payload["end"] = {"date": (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")}
        else:
            if calendar_info.start_time is not None:
                start_dt = datetime.combine(
                    start_dt.date(), calendar_info.start_time, tzinfo=UTC
                )
            if calendar_info.end_time is not None:
                end_dt = datetime.combine(
                    end_dt.date(), calendar_info.end_time, tzinfo=UTC
                )

            # Format datetime as ISO 8601. Add 'Z' manually if UTC, else Google handles offsets.
            # Our backend expects UTC.
            payload["start"] = {
                "dateTime": start_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")
            }
            payload["end"] = {
                "dateTime": end_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")
            }

        if calendar_info.sync_invitees and invitee_emails:
            payload["attendees"] = [{"email": email} for email in invitee_emails]

        return payload
