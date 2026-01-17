"""
Journal domain MCP schemas.

AI-friendly data formats for journal information that provide
structured, contextual data for AI analysis and decision making.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContactRelationshipInfo(BaseModel):
    """Information about a contact relationship in a journal."""

    contact_id: str = Field(description="Unique identifier for the contact")
    contact_name: str = Field(description="Full name of the contact")
    relationship_type: str = Field(
        description="Type of relationship (PARTICIPANT, INVITEE, MENTION, ABOUT)"
    )


class TagInfo(BaseModel):
    """Information about a tag assigned to a journal."""

    tag_id: str = Field(description="Unique identifier for the tag")
    tag_name: str = Field(description="Name of the tag")
    tag_color: str | None = Field(
        default=None, description="Color of the tag (hex code)"
    )


class CalendarInfo(BaseModel):
    """Calendar information for EVENT type journals."""

    calendar_id: str = Field(description="Unique identifier for the calendar")
    calendar_name: str = Field(description="Name of the calendar")
    start_time: str | None = Field(default=None, description="Start time (ISO format)")
    end_time: str | None = Field(default=None, description="End time (ISO format)")
    is_all_day: bool = Field(
        default=False, description="Whether this is an all-day event"
    )
    location: str | None = Field(default=None, description="Event location")


class TypeDataResponse(BaseModel):
    """Type-specific data organized by journal type."""

    EVENT: dict[str, Any] | None = Field(
        default=None, description="Calendar event data"
    )
    MOOD_RATING: dict[str, Any] | None = Field(
        default=None, description="Mood rating data"
    )
    PHOTO_ALBUM: dict[str, Any] | None = Field(
        default=None, description="Photo album data"
    )
    PLAN: dict[str, Any] | None = Field(default=None, description="Plan data")
    TRAVEL: dict[str, Any] | None = Field(default=None, description="Travel data")


class JournalChildSummary(BaseModel):
    """Summary of a child journal."""

    id: str = Field(description="Unique identifier for the child journal")
    title: str = Field(description="Title of the child journal")
    summary: str = Field(description="AI-friendly summary of the child journal")


class JournalResponse(BaseModel):
    """
    AI-friendly journal data format.

    Provides structured journal information optimized for AI consumption,
    including contextual summary information to help AI understand
    the journal entry and its relationships.
    """

    id: str = Field(description="Unique identifier for the journal")
    title: str = Field(description="Title of the journal entry")
    content: str = Field(description="Markdown content of the journal entry")
    event_date_range: dict[str, str] = Field(
        description="Event date range with start and end dates (ISO format)"
    )
    types: list[str] = Field(
        default_factory=list,
        description="List of journal types (e.g., 'EVENT', 'MOOD_RATING', 'NOTE')",
    )
    type_data: TypeDataResponse | None = Field(
        default=None, description="Type-specific data organized by type"
    )
    contacts: list[ContactRelationshipInfo] = Field(
        default_factory=list,
        description="Contacts related to this journal with relationship types",
    )
    tags: list[TagInfo] = Field(
        default_factory=list, description="Tags assigned to this journal"
    )
    calendar: CalendarInfo | None = Field(
        default=None, description="Calendar information for EVENT type journals"
    )
    parent: dict[str, str] | None = Field(
        default=None, description="Parent journal information (id and title)"
    )
    children: list[JournalChildSummary] = Field(
        default_factory=list, description="Child journals (summaries only)"
    )
    summary: str = Field(
        description="AI-friendly summary of the journal including context and key details"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "123",
                "title": "Team Meeting Notes",
                "content": "Discussed Q4 goals and project timelines...",
                "event_date_range": {
                    "start": "2024-01-15T14:00:00Z",
                    "end": "2024-01-15T15:00:00Z",
                },
                "types": ["EVENT", "NOTE"],
                "type_data": {
                    "EVENT": {
                        "calendar_id": "work-calendar",
                        "location": "Conference Room A",
                        "is_all_day": False,
                    }
                },
                "contacts": [
                    {
                        "contact_id": "456",
                        "contact_name": "John Doe",
                        "relationship_type": "PARTICIPANT",
                    }
                ],
                "tags": [{"tag_id": "789", "tag_name": "work", "tag_color": "#FF5733"}],
                "summary": "Team meeting on January 15th discussing Q4 goals with John Doe participating. Tagged as work.",
            }
        }
    )


class JournalSearchResult(BaseModel):
    """AI-friendly journal search result format."""

    id: str = Field(description="Unique identifier for the journal")
    title: str = Field(description="Title of the journal entry")
    content: str = Field(description="Markdown content snippet")
    event_date_range: dict[str, str] = Field(
        description="Event date range with start and end dates"
    )
    types: list[str] = Field(default_factory=list, description="List of journal types")
    tags: list[str] = Field(default_factory=list, description="Tag names")
    highlighted: dict[str, Any] | None = Field(
        default=None, description="Highlighted fields from search with <mark> tags"
    )
    summary: str = Field(
        description="AI-friendly summary of the journal with search context"
    )


class JournalSearchResponse(BaseModel):
    """AI-friendly journal search response format."""

    results: list[JournalSearchResult] = Field(
        description="List of journal search results"
    )
    query: str = Field(description="Original search query")
    total_hits: int = Field(description="Total number of matching journals")
    processing_time_ms: int = Field(
        description="Search processing time in milliseconds"
    )
    summary: str = Field(
        description="AI-friendly summary of search results and context"
    )


class JournalListResponse(BaseModel):
    """AI-friendly journal list response format."""

    journals: list[JournalResponse] = Field(description="List of journals")
    total_count: int = Field(description="Total number of journals")
    page: int = Field(description="Current page number")
    limit: int = Field(description="Number of journals per page")
    summary: str = Field(
        description="AI-friendly summary of the journal list and context"
    )


class JournalCreateRequest(BaseModel):
    """AI-friendly journal creation request format."""

    title: str = Field(description="Journal title (max 500 characters)")
    content: str = Field(description="Markdown content of the journal entry")
    event_date_range: dict[str, str] = Field(
        description="Event date range with 'start' and 'end' keys (ISO format)"
    )
    types: list[str] = Field(
        default_factory=list,
        description="Journal types to add (e.g., ['EVENT', 'MOOD_RATING'])",
    )
    type_data: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Type-specific data organized by type (e.g., {'EVENT': {'calendar_id': '...', 'location': '...'}})",
    )
    contact_relationships: list[dict[str, str]] | None = Field(
        default=None,
        description="Contact relationships (e.g., [{'contact_id': '123', 'relationship_type': 'PARTICIPANT'}])",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tag names to assign (will be created if they don't exist)",
    )
    parent_id: str | None = Field(
        default=None, description="Parent journal ID for hierarchical organization"
    )


class JournalUpdateRequest(BaseModel):
    """AI-friendly journal update request format."""

    journal_id: int = Field(description="ID of the journal to update")
    title: str | None = Field(default=None, description="Updated title")
    content: str | None = Field(default=None, description="Updated content")
    event_date_range: dict[str, str] | None = Field(
        default=None, description="Updated event date range"
    )
