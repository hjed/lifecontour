"""
Journal domain MCP schemas.

Provides AI-optimized Pydantic schemas for journal MCP responses.
All schemas include contextual summaries to help AI understand the data.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventDateRangeSchema(BaseModel):
    """AI-friendly event date range format."""

    start: datetime = Field(description="Start datetime of the event (UTC)")
    end: datetime = Field(description="End datetime of the event (UTC)")


class ContactRelationshipSchema(BaseModel):
    """AI-friendly contact relationship format."""

    id: int = Field(description="Contact ID")
    name: str = Field(description="Contact full name")
    relationship_type: str = Field(
        description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
    )


class CalendarSchema(BaseModel):
    """AI-friendly calendar format."""

    id: str = Field(description="Calendar UUID")
    name: str = Field(description="Calendar name")
    color: str | None = Field(default=None, description="Calendar color (hex)")


class JournalChildSummary(BaseModel):
    """AI-friendly child journal summary."""

    id: int = Field(description="Journal ID")
    title: str = Field(description="Journal title")
    summary: str = Field(description="Brief summary of the child journal")


class JournalResponse(BaseModel):
    """
    AI-friendly journal data format.

    Provides structured journal information optimized for AI consumption,
    including contextual summary information and embedded related data
    to minimize API calls.
    """

    id: int = Field(description="Unique identifier for the journal")

    title: str = Field(description="Journal title")

    content: str = Field(description="Journal content (markdown)")

    summary: str = Field(
        description="AI-friendly summary of journal with context and key information"
    )

    event_date_range: EventDateRangeSchema = Field(
        description="Event date range (start and end)"
    )

    types: list[str] = Field(default_factory=list, description="List of journal types")

    type_data: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Type-specific data organized by type (e.g., EVENT: {calendar_id: ...})",
    )

    contacts: list[ContactRelationshipSchema] = Field(
        default_factory=list,
        description="Contact relationships (participants, invitees, mentions, about)",
    )

    tags: list[str] = Field(
        default_factory=list, description="List of tag names assigned to journal"
    )

    calendar: CalendarSchema | None = Field(
        default=None, description="Calendar information (if EVENT type)"
    )

    parent: JournalChildSummary | None = Field(
        default=None, description="Parent journal summary (if child journal)"
    )

    children: list[JournalChildSummary] = Field(
        default_factory=list, description="Child journal summaries (if parent journal)"
    )

    created_at: datetime = Field(description="Creation timestamp (UTC)")

    updated_at: datetime = Field(description="Last update timestamp (UTC)")


class JournalSearchResult(BaseModel):
    """AI-friendly journal search result format."""

    id: int = Field(description="Journal ID")
    title: str = Field(description="Journal title")
    content_excerpt: str = Field(description="Excerpt of journal content")
    event_date_range: EventDateRangeSchema = Field(description="Event date range")
    types: list[str] = Field(default_factory=list, description="Journal types")
    tags: list[str] = Field(default_factory=list, description="Tag names")
    highlighted: dict[str, str] = Field(
        default_factory=dict, description="Search highlighting information"
    )
    summary: str = Field(description="AI-friendly summary with search context")


class JournalSearchResponse(BaseModel):
    """AI-friendly journal search response format."""

    results: list[JournalSearchResult] = Field(
        description="List of journal search results"
    )
    query: str | None = Field(default=None, description="Original search query")
    total_hits: int = Field(description="Total number of matching journals")
    processing_time_ms: int = Field(
        description="Search processing time in milliseconds"
    )
    summary: str = Field(
        description="AI-friendly summary of search results and context"
    )


class JournalCreateRequest(BaseModel):
    """AI-friendly journal creation request format."""

    title: str = Field(description="Journal title")
    content: str = Field(description="Journal content (markdown)")
    event_date_range: EventDateRangeSchema = Field(description="Event date range")
    types: list[str] = Field(default_factory=list, description="Journal types to add")
    type_data: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Type-specific data (e.g., EVENT: {calendar_id: uuid})",
    )
    contact_relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Contact relationships [{contact_id: int, relationship_type: str}]",
    )
    tags: list[str] = Field(default_factory=list, description="Tag names to assign")
    parent_id: int | None = Field(default=None, description="Parent journal ID")


class JournalUpdateRequest(BaseModel):
    """AI-friendly journal update request format."""

    title: str | None = Field(default=None, description="Updated title")
    content: str | None = Field(default=None, description="Updated content")
    event_date_range: EventDateRangeSchema | None = Field(
        default=None, description="Updated event date range"
    )
    types: list[str] | None = Field(default=None, description="Replace all types")
    type_data: dict[str, dict[str, Any]] | None = Field(
        default=None, description="Update type-specific data"
    )
    contact_relationships: list[dict[str, Any]] | None = Field(
        default=None, description="Replace all contact relationships"
    )
    tags: list[str] | None = Field(default=None, description="Replace all tags")
