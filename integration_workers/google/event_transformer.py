import uuid
from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import CalendarInfo, EventDateRange, Journal

from calendar_models import GoogleEvent, GoogleEventStartEnd


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

        date_range = EventDateRange(start=start_dt, end=end_dt)

        journal = Journal(
            user_id=user_id,
            title=google_event.summary or "Untitled Event",
            content=google_event.description or "No description provided.",
            event_date_range=date_range,
        )

        calendar_info = CalendarInfo(
            journal_id=None,
            calendar_id=calendar_id,
            start_time=None if is_all_day else start_dt.time() if start_dt else None,
            end_time=None if is_all_day else end_dt.time() if end_dt else None,
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
            # All-day event
            try:
                dt_naive = datetime.strptime(time_data.date, "%Y-%m-%d")
                dt_utc = dt_naive.replace(tzinfo=UTC)
                return dt_utc, True
            except ValueError:
                return None, False
        elif time_data.date_time:
            # Timed event
            try:
                date_time_str = time_data.date_time
                if date_time_str.endswith("Z"):
                    date_time_str = date_time_str[:-1] + "+00:00"
                dt = datetime.fromisoformat(date_time_str)
                # If the parsing didn't result in an aware datetime and timeZone is provided, we could attach it.
                # However, fromisoformat with Z or +00:00 will handle aware. If missing entirely, assume UTC.
                if dt.tzinfo is None:
                    if time_data.time_zone:
                        try:
                            from zoneinfo import ZoneInfo
                            tz = ZoneInfo(time_data.time_zone)
                            dt = dt.replace(tzinfo=tz)
                        except Exception:
                            dt = dt.replace(tzinfo=UTC)
                    else:
                        dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC), False
            except ValueError:
                return None, False

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
                start_dt = datetime.combine(start_dt.date(), calendar_info.start_time, tzinfo=UTC)
            if calendar_info.end_time is not None:
                end_dt = datetime.combine(end_dt.date(), calendar_info.end_time, tzinfo=UTC)

            # Format datetime as ISO 8601. Add 'Z' manually if UTC, else Google handles offsets.
            # Our backend expects UTC.
            payload["start"] = {"dateTime": start_dt.isoformat().replace("+00:00", "Z")}
            payload["end"] = {"dateTime": end_dt.isoformat().replace("+00:00", "Z")}

        if calendar_info.sync_invitees and invitee_emails:
            payload["attendees"] = [{"email": email} for email in invitee_emails]

        return payload
