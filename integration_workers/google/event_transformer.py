import uuid
from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import (
    CalendarInfo,
    EventDateRange,
    Journal,
    JournalValidationError,
)
from core_shared.models.journals.event_state import EventState

from calendar_models import GoogleEvent, GoogleEventStartEnd

UTC_OFFSET_SUFFIX = "+00:00"


class GoogleEventTransformer:
    """Transforms events between Google Calendar API and internal Journal formats."""

    def transform_event(
        self,
        google_event: GoogleEvent,
        user_id: str,
        calendar_id: uuid.UUID,
        self_email: str | None = None,
    ) -> tuple[Journal, CalendarInfo] | None:
        """
        Transform a GoogleEvent into a Journal and CalendarInfo tuple.

        Args:
            google_event: The Google Calendar event to transform
            user_id: The user ID for the journal
            calendar_id: The calendar UUID for the CalendarInfo
            self_email: The user's email to match against attendees for
                        responseStatus → event_state mapping

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

        event_state = self._resolve_event_state(google_event, self_email)

        # Extract timezone from Google event (prefer start timezone)
        event_timezone = self._extract_timezone(google_event)

        local_start_dt = self._extract_local_datetime(start_dt, event_timezone)
        local_end_dt = self._extract_local_datetime(end_dt, event_timezone)

        if is_all_day:
            start_time = None
            end_time = None
        else:
            start_time = (
                local_start_dt.time().replace(tzinfo=None) if local_start_dt else None
            )
            end_time = (
                local_end_dt.time().replace(tzinfo=None) if local_end_dt else None
            )

        calendar_info = CalendarInfo(
            journal_id=None,
            calendar_id=calendar_id,
            start_time=start_time,
            end_time=end_time,
            is_all_day=is_all_day,
            location=google_event.location,
            timezone=event_timezone,
            event_state=event_state,
            event_start_date=local_start_dt.date() if local_start_dt else None,
            event_end_date=local_end_dt.date() if local_end_dt else None,
        )

        return journal, calendar_info

    def _extract_local_datetime(
        self, dt_utc: datetime | None, timezone_str: str | None
    ) -> datetime | None:
        if not dt_utc:
            return None
        if not timezone_str:
            return dt_utc
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(timezone_str)
            return dt_utc.astimezone(tz)
        except Exception:  # noqa: BLE001
            return dt_utc

    def _extract_timezone(self, google_event: GoogleEvent) -> str | None:
        """Extract IANA timezone from Google event start/end.

        Returns the timezone string from start.timeZone (preferred) or end.timeZone.
        Returns None for all-day events (date-only) or when no timezone is specified.
        """
        # All-day events use date fields, not dateTime — timezone is not meaningful
        if google_event.start and google_event.start.date:
            return None
        if google_event.start and google_event.start.time_zone:
            return google_event.start.time_zone
        if google_event.end and google_event.end.time_zone:
            return google_event.end.time_zone
        return None

    def _resolve_event_state(
        self,
        google_event: GoogleEvent,
        self_email: str | None,
    ) -> EventState:
        """Resolve event_state from Google event status + self-attendee responseStatus.

        Priority:
        1. Event-level status "tentative" → TENTATIVE
        2. Self-attendee responseStatus "needsAction" → INVITED
        3. Self-attendee responseStatus "tentative" → TENTATIVE
        4. Self-attendee responseStatus "declined" → keep event-level mapping
        5. Default: CONFIRMED
        """
        # Map event-level status
        if google_event.status == "tentative":
            return EventState.TENTATIVE

        base_state = EventState.CONFIRMED

        # Check self-attendee responseStatus override
        if self_email and google_event.attendees:
            for attendee in google_event.attendees:
                if attendee.email.lower() == self_email.lower():
                    response = attendee.response_status
                    if response == "needsAction":
                        return EventState.INVITED
                    elif response == "tentative":
                        return EventState.TENTATIVE
                    # "accepted" or "declined" → use base_state
                    break

        return base_state

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
            from datetime import date

            parsed_date = date.fromisoformat(date_str)
            dt_utc = datetime(
                parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
            )
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
                    except Exception:  # noqa: BLE001
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

            local_start_dt = self._extract_local_datetime(
                start_dt, calendar_info.timezone
            )
            local_end_dt = self._extract_local_datetime(end_dt, calendar_info.timezone)

            payload["start"] = {
                "date": local_start_dt.strftime("%Y-%m-%d")
                if local_start_dt
                else start_dt.strftime("%Y-%m-%d")
            }
            payload["end"] = {
                "date": ((local_end_dt or end_dt) + timedelta(days=1)).strftime(
                    "%Y-%m-%d"
                )
            }
        else:
            from datetime import tzinfo

            tz: tzinfo = UTC
            if calendar_info.timezone:
                try:
                    from zoneinfo import ZoneInfo

                    tz = ZoneInfo(calendar_info.timezone)
                except Exception:  # noqa: BLE001
                    pass

            if calendar_info.start_time is not None:
                local_start_dt = start_dt.astimezone(tz)
                start_dt = datetime.combine(
                    local_start_dt.date(), calendar_info.start_time, tzinfo=tz
                ).astimezone(UTC)
            if calendar_info.end_time is not None:
                local_end_dt = end_dt.astimezone(tz)
                end_dt = datetime.combine(
                    local_end_dt.date(), calendar_info.end_time, tzinfo=tz
                ).astimezone(UTC)

            # Format datetime as ISO 8601. Add 'Z' manually if UTC, else Google handles offsets.
            # Our backend expects UTC.
            start_payload: dict[str, str] = {
                "dateTime": start_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")
            }
            end_payload: dict[str, str] = {
                "dateTime": end_dt.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")
            }

            # Include timezone if set on the calendar info
            if calendar_info.timezone:
                start_payload["timeZone"] = calendar_info.timezone
                end_payload["timeZone"] = calendar_info.timezone

            payload["start"] = start_payload
            payload["end"] = end_payload

        if calendar_info.sync_invitees and invitee_emails:
            payload["attendees"] = [{"email": email} for email in invitee_emails]

        return payload

    @staticmethod
    def extract_contact_relationships(
        google_event: GoogleEvent,
    ) -> list[dict[str, str]]:
        """Extract contact relationships (invitees) from a Google Event with status and role."""
        from core_shared.models.journals.attendee_status import AttendeeStatus
        from core_shared.models.journals.contact_event_role import ContactEventRole

        relationships: list[dict[str, str]] = []
        if not google_event.attendees:
            return relationships

        for attendee in google_event.attendees:
            if not attendee.email:
                continue

            # Default to NO_REPLY
            status = AttendeeStatus.NO_REPLY
            if attendee.response_status == "accepted":
                status = AttendeeStatus.ATTENDING
            elif attendee.response_status == "needsAction":
                status = AttendeeStatus.NO_REPLY
            elif attendee.response_status == "tentative":
                status = AttendeeStatus.MAYBE
            elif attendee.response_status == "declined":
                status = AttendeeStatus.DECLINED

            # Map organizer
            role = ContactEventRole.ORGANISER if attendee.organizer else None

            rel = {
                "email": attendee.email,
                "relationship_type": "INVITEE",
                "status": status.value,
            }
            if role:
                rel["role"] = role.value

            relationships.append(rel)

        return relationships
