"""
Journal domain MCP schemas.

Provides AI-optimized Pydantic schemas for journal MCP responses.
All schemas include contextual summaries to help AI understand the data.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Field description constants
JOURNAL_TITLE_DESC = "Journal title"
JOURNAL_ID_DESC = "Journal ID"
EVENT_DATE_RANGE_DESC = "Event date range"

TOTAL_DISTANCE_DESC = "Total distance in metres"
TOTAL_DURATION_DESC = "Total duration in seconds"
TOTAL_ELEVATION_GAIN_DESC = "Total elevation gain in metres"


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
    status: str | None = Field(
        default=None, description="Attendee status (ATTENDING, MAYBE, etc.)"
    )
    role: str | None = Field(
        default=None, description="Event role (ORGANISER, FACILITATOR_HELPER, etc.)"
    )


@dataclass
class ContactRelationshipSummary:
    """Internal structure for passing contact relationships to the MCP converter."""

    id: int
    name: str
    relationship_type: str
    status: str | None = None
    role: str | None = None


class CalendarSchema(BaseModel):
    """AI-friendly calendar format."""

    id: str = Field(description="Calendar UUID")
    name: str = Field(description="Calendar name")
    color: str | None = Field(default=None, description="Calendar color (hex)")


class JournalChildSummary(BaseModel):
    """AI-friendly child journal summary."""

    id: int = Field(description=JOURNAL_ID_DESC)
    title: str = Field(description=JOURNAL_TITLE_DESC)
    summary: str = Field(description="Brief summary of the child journal")


class JournalResponse(BaseModel):
    """
    AI-friendly journal data format.

    Provides structured journal information optimized for AI consumption,
    including contextual summary information and embedded related data
    to minimize API calls.
    """

    id: int = Field(description="Unique identifier for the journal")

    title: str = Field(description=JOURNAL_TITLE_DESC)

    content: str = Field(description="Journal content (markdown)")

    summary: str = Field(
        description="AI-friendly summary of journal with context and key information"
    )

    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)

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

    id: int = Field(description=JOURNAL_ID_DESC)
    title: str = Field(description=JOURNAL_TITLE_DESC)
    content_excerpt: str = Field(description="Excerpt of journal content")
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    types: list[str] = Field(default_factory=list, description="Journal types")
    tags: list[str] = Field(default_factory=list, description="Tag names")
    highlighted: dict[str, str] = Field(
        default_factory=dict, description="Search highlighting information"
    )
    summary: str | None = Field(
        default=None, description="AI-friendly summary with search context"
    )


class JournalHierarchyNode(JournalSearchResult):
    """AI-friendly journal hierarchy node format."""

    depth: int = Field(description="Nesting level in the hierarchy")
    children_count: int = Field(description="Number of direct children")
    children: list["JournalHierarchyNode"] = Field(
        default_factory=list, description="Child journals"
    )


class JournalHierarchyResponse(BaseModel):
    """AI-friendly journal hierarchy response format."""

    nodes: list[JournalHierarchyNode] = Field(description="Root hierarchy nodes")
    total_nodes: int = Field(description="Total number of journals returned")
    processing_time_ms: int = Field(description="Processing time in ms")
    summary: str = Field(description="AI-friendly summary of hierarchy")


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


class JournalDateWindowResponse(BaseModel):
    """AI-friendly date-window journal browsing response.

    Returns journals within a computed date window anchored on a given date.
    Designed for time-oriented journal browsing (e.g. infinite scroll).
    """

    results: list[JournalSearchResult] = Field(
        description="Journals within the date window"
    )
    window_start: str = Field(description="Window start date (ISO format)")
    window_end: str = Field(description="Window end date (ISO format)")
    anchor_date: str = Field(description="The anchor date used for the window")
    total_count: int = Field(description="Total journals in the window")
    has_more: bool = Field(
        description="Whether there are more journals beyond the current offset+limit"
    )
    summary: str = Field(description="AI-friendly summary of the date window results")


class ActivityTotals(BaseModel):
    """Aggregate activity metrics."""

    distance: int = Field(default=0, description=TOTAL_DISTANCE_DESC)
    duration: int = Field(default=0, description=TOTAL_DURATION_DESC)
    elevation_gain: int = Field(default=0, description=TOTAL_ELEVATION_GAIN_DESC)
    calories: int = Field(default=0, description="Total calories burned")


class ActivityTypeStats(BaseModel):
    """Aggregated statistics for a specific activity type."""

    activity_type: str = Field(description="Activity type name")
    count: int = Field(description="Number of activities of this type")
    total_distance: int = Field(default=0, description=TOTAL_DISTANCE_DESC)
    total_duration: int = Field(default=0, description=TOTAL_DURATION_DESC)
    total_elevation_gain: int = Field(default=0, description=TOTAL_ELEVATION_GAIN_DESC)
    total_calories: int = Field(default=0, description="Total calories burned")


class ActivityPersonalRecord(BaseModel):
    """Personal record entry for an activity metric."""

    activity_type: str = Field(description="Activity type for the record")
    journal_id: int = Field(description="Journal identifier for the record")
    journal_title: str = Field(description="Journal title for the record")
    value: int = Field(description="Record value for the metric")


class ActivityStatsResponse(BaseModel):
    """AI-friendly activity statistics response."""

    total_activities: int = Field(description="Total number of matched activities")
    overall_totals: ActivityTotals = Field(
        description="Overall totals across activities"
    )
    activity_types: list[ActivityTypeStats] = Field(
        default_factory=list, description="Per-activity-type breakdown"
    )
    personal_records: dict[str, ActivityPersonalRecord | None] = Field(
        default_factory=dict,
        description="Named personal records such as longest distance or duration",
    )
    summary: str = Field(description="AI-friendly summary of activity statistics")


class ActivityTrendPeriod(BaseModel):
    """Aggregated trend bucket for activity analytics."""

    period_start: str = Field(description="Bucket start date in ISO format")
    activity_count: int = Field(description="Number of activities in the bucket")
    total_distance: int = Field(default=0, description=TOTAL_DISTANCE_DESC)
    total_duration: int = Field(default=0, description=TOTAL_DURATION_DESC)
    total_elevation_gain: int = Field(default=0, description=TOTAL_ELEVATION_GAIN_DESC)


class ActivityTrendsResponse(BaseModel):
    """AI-friendly activity trends response."""

    interval: str = Field(description="Trend interval: day, week, month, or year")
    total_activities: int = Field(description="Total number of matched activities")
    periods: list[ActivityTrendPeriod] = Field(
        default_factory=list, description="Trend buckets ordered by period"
    )
    summary: str = Field(description="AI-friendly summary of trend results")


class RouteSummary(BaseModel):
    """Summary of a route referenced by activities."""

    id: str = Field(description="Route UUID")
    name: str = Field(description="Route name")
    description: str | None = Field(default=None, description="Route description")


class RouteHistoryEntry(BaseModel):
    """Activity entry referencing a route."""

    journal_id: int = Field(description="Journal identifier")
    journal_title: str = Field(description="Journal title")
    activity_type: str = Field(description="Resolved activity type")
    event_date_range: EventDateRangeSchema = Field(
        description="Journal event date range"
    )
    distance: int | None = Field(default=None, description="Distance in metres")
    duration: int | None = Field(default=None, description="Duration in seconds")


class RouteHistoryResponse(BaseModel):
    """AI-friendly route usage history response."""

    route: RouteSummary = Field(description="Route summary")
    usage_count: int = Field(description="Total number of matching activity entries")
    activity_types: list[str] = Field(
        default_factory=list, description="Distinct activity types using the route"
    )
    entries: list[RouteHistoryEntry] = Field(
        default_factory=list, description="Route activity entries ordered newest first"
    )
    summary: str = Field(description="AI-friendly summary of route usage")


class JournalCreateRequest(BaseModel):
    """AI-friendly journal creation request format."""

    title: str = Field(description=JOURNAL_TITLE_DESC)
    content: str = Field(description="Journal content (markdown)")
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    types: list[str] = Field(
        default_factory=list,
        description="Journal types to add. Valid values: NOTE, EVENT, MOOD_RATING, "
        "PLAN, TRAVEL, PHOTO_ALBUM, FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, "
        "JOGGING, ABSEILING_TRIP, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING. "
        "Dependencies are added automatically.",
    )
    type_data: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Type-specific data keyed by type name. "
        "Call list_journal_types to see available fields per type. "
        'Example: {"EVENT": {"calendar_id": "uuid"}, '
        '"MOOD_RATING": {"mood_value": 7}}',
    )
    contact_relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Contact relationships. Each dict: {contact_id: int, "
        "relationship_type: PARTICIPANT|INVITEE|MENTION|ABOUT, "
        "status?: ATTENDING|ATTENDED|MAYBE|NO_REPLY|DECLINED, "
        "role?: ORGANISER|FACILITATOR_HELPER}",
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
    types: list[str] | None = Field(
        default=None,
        description="Replace all types. Valid values: NOTE, EVENT, MOOD_RATING, "
        "PLAN, TRAVEL, PHOTO_ALBUM, FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, "
        "JOGGING, ABSEILING_TRIP, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING. "
        "Dependencies are added automatically.",
    )
    type_data: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Update type-specific data keyed by type name. "
        "Call list_journal_types to see available fields per type.",
    )
    contact_relationships: list[dict[str, Any]] | None = Field(
        default=None,
        description="Replace all contact relationships. Each dict: {contact_id: int, "
        "relationship_type: PARTICIPANT|INVITEE|MENTION|ABOUT, "
        "status?: ATTENDING|ATTENDED|MAYBE|NO_REPLY|DECLINED, "
        "role?: ORGANISER|FACILITATOR_HELPER}",
    )
    tags: list[str] | None = Field(default=None, description="Replace all tags")
    parent_id: int | None = Field(default=None, description="Parent journal ID")


class MergeJournalMCPRequest(BaseModel):
    """AI-friendly journal merge request format.

    Parsed from the JSON string provided by the AI agent when calling
    the ``merge_journals`` MCP tool.
    """

    source_journal_id: int = Field(
        description="ID of the journal to merge into the target (this journal will be deleted)"
    )
    overrides: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional explicit conflict resolution overrides. Supported keys: "
            "'title' (str), 'content' (str), 'event_date_range' ({start, end}), "
            "'type_data' ({TYPE: {field: value}})"
        ),
    )


class MergeCandidateResult(BaseModel):
    """AI-friendly merge candidate summary."""

    id: int = Field(description=JOURNAL_ID_DESC)
    title: str = Field(description=JOURNAL_TITLE_DESC)
    content_excerpt: str = Field(description="First ~200 chars of content")
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    types: list[str] = Field(default_factory=list, description="Journal types")
    tags: list[str] = Field(default_factory=list, description="Tag names")
    summary: str = Field(description="AI-friendly summary of why this is a candidate")


class MergeCandidatesResponse(BaseModel):
    """AI-friendly merge candidates response."""

    target_journal_id: int = Field(
        description="The journal for which candidates were found"
    )
    target_title: str = Field(description="Title of the target journal")
    candidates: list[MergeCandidateResult] = Field(
        description="Journals that could potentially be merged with the target"
    )
    summary: str = Field(
        description="AI-friendly summary of merge candidates and recommendations"
    )


class DailySummaryMCPResponse(BaseModel):
    """AI-friendly daily summary response format."""

    summary_date: str = Field(description="Date of the summary in ISO format")
    summary_text: str | None = Field(
        default=None, description="The AI-generated daily summary text, if available"
    )
    journal_count: int = Field(description="Number of journals on this day")
    event_count: int = Field(description="Number of events on this day")
    contact_count: int = Field(
        description="Number of contacts mentioned or met on this day"
    )
    mood_average: float | None = Field(
        default=None, description="Average mood score for the day (0.0 to 1.0)"
    )
    status: str = Field(
        description="Status of the summary (e.g. generated, pending, failed, disabled)"
    )
    summary: str = Field(
        description="AI-friendly summary of the daily summary results and context"
    )
