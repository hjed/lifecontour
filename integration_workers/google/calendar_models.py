from typing import Any

from pydantic import BaseModel, Field


class GoogleCalendar(BaseModel):
    """Transformer-facing model for a Google Calendar."""

    id: str = Field(..., description="The unique identifier for the calendar")
    summary: str = Field(..., description="The title of the calendar")
    description: str | None = Field(None, description="The description of the calendar")
    primary: bool = Field(False, description="Whether this is the primary calendar")
    access_role: str | None = Field(
        None, description="The user's access role for this calendar"
    )


class GoogleEventStartEnd(BaseModel):
    """Start or end time for a Google Event."""

    date: str | None = Field(
        None,
        description="The date, in the format 'yyyy-mm-dd', if this is an all-day event",
    )
    date_time: str | None = Field(
        None, alias="dateTime", description="The time of the event (ISO 8601)"
    )
    time_zone: str | None = Field(
        None,
        alias="timeZone",
        description="The time zone in which the time is specified",
    )


class GoogleEventAttendee(BaseModel):
    """Attendee of a Google Calendar event."""

    email: str = Field(..., description="The attendee's email address")
    response_status: str | None = Field(
        None,
        alias="responseStatus",
        description="The attendee's response status (needsAction, declined, tentative, accepted)",
    )


class GoogleEvent(BaseModel):
    """Transformer-facing model for a Google Event."""

    id: str = Field(..., description="The unique identifier for the event")
    status: str | None = Field(
        None,
        description="Status of the event (e.g., 'confirmed', 'tentative', 'cancelled')",
    )
    html_link: str | None = Field(
        None,
        alias="htmlLink",
        description="An absolute link to this event in the Google Calendar Web UI",
    )
    created: str | None = Field(
        None, description="Creation time of the event (ISO 8601)"
    )
    updated: str | None = Field(
        None, description="Last modification time of the event (ISO 8601)"
    )
    summary: str | None = Field(None, description="Title of the event")
    description: str | None = Field(None, description="Description of the event")
    location: str | None = Field(
        None, description="Geographic location of the event as free-form text"
    )
    start: GoogleEventStartEnd | None = Field(
        None, description="The start time of the event"
    )
    end: GoogleEventStartEnd | None = Field(
        None, description="The end time of the event"
    )
    etag: str | None = Field(None, description="ETag of the resource")
    attendees: list[GoogleEventAttendee] = Field(
        default_factory=list, description="The attendees of the event"
    )

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "GoogleEvent":
        """Create a GoogleEvent from a raw API response dictionary."""
        return cls(**data)
