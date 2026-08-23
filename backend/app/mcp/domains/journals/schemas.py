"""
Journal domain MCP schemas.

Provides AI-optimized Pydantic schemas for journal MCP responses.
All schemas include contextual summaries to help AI understand the data.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from core_shared.models.journals import FitnessMergeMode, JournalType
from pydantic import BaseModel, Field

# Field description constants
JOURNAL_TITLE_DESC = "Journal title"
JOURNAL_ID_DESC = "Journal ID"
EVENT_DATE_RANGE_DESC = "Event date range"

TOTAL_DISTANCE_DESC = "Total distance in metres"
TOTAL_DURATION_DESC = "Total duration in seconds"
TOTAL_ELEVATION_GAIN_DESC = "Total elevation gain in metres"


# Every journal type name, for tool descriptions. Generated so a new type can
# never be missing from the documented list.
VALID_JOURNAL_TYPE_NAMES = ", ".join(journal_type.name for journal_type in JournalType)


# Closed vocabularies, spelled out as Literal types so FastMCP publishes them as
# JSON-schema ``enum`` lists (an agent sees the options before calling rather
# than discovering them through validation failures). Each must match the
# corresponding VALID_* list in core_shared; tests/unit/mcp/test_journal_enums.py
# fails if they drift.
AnchorType = Literal[
    "chains",
    "double bolt",
    "single bolt",
    "sling on tree",
    "sling on log",
    "sling on boulder",
    "sling on bollard",
    "artificial removable",
]
AnchorLocation = Literal["TR", "TL", "Centre"]
PitchType = Literal["abseil", "jump", "down_climb"]
CanyonType = Literal["vertical", "aquatic", "mixed"]
ClimbingType = Literal["sport", "trad", "bouldering", "top_rope"]
TemplateType = Literal["abseiling", "canyoning", "caving", "climbing"]


class TemplatePitchInput(BaseModel):
    """One pitch of an activity template, as accepted by create/update_template."""

    pitch_number: int = Field(description="Pitch number in sequence (1-based)")
    height: int | None = Field(default=None, description="Pitch height in metres")
    anchor_location: AnchorLocation | None = Field(
        default=None,
        description="Where the anchor sits (TR = top right, TL = top left)",
    )
    anchor_type: AnchorType | None = Field(default=None, description="Anchor type")
    did_rescue: bool | None = Field(default=None, description="A rescue occurred")
    did_setup: bool | None = Field(default=None, description="User set up the anchor")
    notes: str | None = Field(default=None, description="Short notes for the pitch")
    pitch_type: PitchType | None = Field(
        default=None,
        description="How the pitch is descended (null is treated as abseil)",
    )


class ExternalLinkSchema(BaseModel):
    """AI-friendly external system link format.

    Represents a link to an external system (e.g. Strava, Google Calendar)
    that is associated with a journal entry.
    """

    source: str = Field(
        description="Integration source identifier (e.g. 'strava', 'google_calendar')"
    )
    url: str | None = Field(
        default=None,
        description="Clickable URL to the external record, or null if not constructable",
    )
    external_id: str = Field(
        description="The external system's identifier for the entity"
    )


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

    series: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "Series memberships as {id, name} refs — recurring/related groups "
            "this journal belongs to (e.g. a recurring calendar event or a "
            "manually grouped series of appointments)"
        ),
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

    external_links: list[ExternalLinkSchema] = Field(
        default_factory=list,
        description=(
            "External system links (e.g. Strava activity, Google Calendar event). "
            "Always populated on get/create/update responses; search results "
            "omit links — call get_journal for them."
        ),
    )

    external_links_preserved: bool | None = Field(
        default=None,
        description=(
            "Update responses only: true when the journal had external links "
            "before the update and every one of them is still present; false "
            "when a link was lost; null on create/read responses. Updates never "
            "touch integration links unless a type that carries one is removed."
        ),
    )

    types_removed: list[str] = Field(
        default_factory=list,
        description=(
            "Types dropped by this update (update responses only). Types that "
            "remain — including dependencies shared between the old and new "
            "types — keep their type_data untouched."
        ),
    )

    type_data_discarded: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "For each type in types_removed, the type_data fields that held a "
            "value and were discarded with it (update responses only)."
        ),
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
    children: list[JournalHierarchyNode] = Field(
        default_factory=list, description="Child journals"
    )


class JournalHierarchyResponse(BaseModel):
    """AI-friendly journal hierarchy response format."""

    nodes: list[JournalHierarchyNode] = Field(description="Root hierarchy nodes")
    total_nodes: int = Field(description="Total number of journals returned")
    processing_time_ms: int = Field(description="Processing time in ms")
    summary: str = Field(description="AI-friendly summary of hierarchy")


class SearchDiagnostics(BaseModel):
    """Why a search came back empty, so an agent can tell "nothing exists"
    from "wrong query" instead of acting on a silent zero."""

    search_backend: str = Field(
        description="Which backend answered: 'meilisearch' (word matching, typo "
        "tolerance) or 'database' (exact listing without a text query)"
    )
    filters: dict[str, Any] = Field(
        default_factory=dict, description="Every filter that was applied"
    )
    journals_for_user_total: int = Field(
        description="How many journals the user has in total (0 means the "
        "account is empty, any other number means the filters excluded them)"
    )
    journals_linked_to_source: int | None = Field(
        default=None,
        description="When integration_source was given: how many journals are "
        "linked to that source at all, ignoring the query",
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Concrete next steps to try"
    )


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
    diagnostics: SearchDiagnostics | None = Field(
        default=None,
        description="Present only when total_hits is 0: what was searched, "
        "how many journals exist regardless, and what to try next",
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
    diagnostics: SearchDiagnostics | None = Field(
        default=None,
        description="Present only when total_count is 0: the window and filters "
        "used, how many journals exist regardless, and what to try next",
    )


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


class JournalHistoryEntry(BaseModel):
    """A single field-level change in a journal's history.

    Field-for-field parity with the REST ``HistoryAttributes`` schema so AI
    agents see the same detail and provenance available in the UI.
    """

    entity_type: str = Field(
        description="Entity the change applies to (journal, route, gear)"
    )
    entity_id: int = Field(description="Identifier of the changed entity")
    field_name: str = Field(
        description=(
            "Field that changed. Route/gear changes are tagged to the journal "
            "with context (e.g. 'route:<id>:name')."
        )
    )
    old_value: str | None = Field(default=None, description="Previous value")
    new_value: str | None = Field(default=None, description="New value")
    changed_by: str | None = Field(
        default=None, description="Who or what made the change"
    )
    source: str = Field(
        description="Provenance (ui, mcp, strava, google_calendar, immich, system, ...)"
    )
    created_at: datetime | None = Field(
        default=None, description="When the change actually occurred"
    )


class JournalHistoryResponse(BaseModel):
    """AI-friendly journal field-level history response.

    Matches the REST ``GET /api/journals/{id}/history`` endpoint: paginated,
    most-recent-first, field-level entries with provenance.
    """

    journal_id: int = Field(description="Journal identifier")
    total_count: int = Field(description="Total number of history entries")
    page: int = Field(description="Current page number (1-based)")
    limit: int = Field(description="Entries per page")
    entries: list[JournalHistoryEntry] = Field(
        default_factory=list,
        description="History entries ordered newest first for this page",
    )
    summary: str = Field(description="AI-friendly summary of the journal's history")


class JournalCreateRequest(BaseModel):
    """AI-friendly journal creation request format."""

    title: str = Field(description=JOURNAL_TITLE_DESC)
    content: str = Field(description="Journal content (markdown)")
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    types: list[str] = Field(
        default_factory=list,
        description="Journal types to add. Valid values: "
        + VALID_JOURNAL_TYPE_NAMES
        + ". Dependencies are added automatically. NOTE is implicit (a journal "
        "with no typed data) and is ignored when combined with other types.",
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
        description="Replace all types. Valid values: "
        + VALID_JOURNAL_TYPE_NAMES
        + ". Dependencies are added automatically, and types that remain keep "
        "their type_data. NOTE is implicit (a journal with no typed data) and is "
        "ignored when combined with other types.",
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
    fitness_merge_mode: FitnessMergeMode = Field(
        default=FitnessMergeMode.REPLACE,
        description=(
            "How to reconcile fitness data when both journals have it. "
            "'replace' (default) keeps the target's metrics and drops the "
            "source's integration links — right for a duplicate or re-import. "
            "'additive' sums distance, duration, elevation and calories, "
            "combines heart rates, and keeps both journals' Strava activities "
            "linked — right when the two journals are two parts of one outing."
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


class TemplatePitchMCPSchema(BaseModel):
    """AI-friendly pitch format."""

    pitch_number: int = Field(description="Pitch number in sequence")
    height: int = Field(description="Height of pitch in metres")
    anchor_location: str | None = Field(
        default=None, description="Anchor location (see list_journal_types enums)"
    )
    anchor_type: str | None = Field(
        default=None, description="Anchor type (see list_journal_types enums)"
    )
    did_rescue: bool = Field(default=False, description="Did rescue occur")
    did_setup: bool = Field(default=False, description="Did user setup")
    notes: str | None = Field(
        default=None, description="Optional short notes for the pitch"
    )
    pitch_type: str | None = Field(
        default=None,
        description=(
            "How the pitch is descended: abseil, jump, or down_climb "
            "(null is treated as abseil)"
        ),
    )


class ActivityTemplateMCPResponse(BaseModel):
    """AI-friendly activity template response."""

    id: str = Field(description="Template UUID")
    name: str = Field(description="Template name")
    template_type: str = Field(
        description="Type of template (canyoning, climbing, etc)"
    )
    region: str | None = Field(default=None, description="Region")
    description: str | None = Field(default=None, description="Description")
    french_grade: str | None = Field(default=None, description="French grade")
    canyon_type: str | None = Field(
        default=None, description="Canyon type: vertical, aquatic or mixed"
    )
    water_gauge_name: str | None = Field(default=None, description="Water gauge name")
    is_vertical: bool | None = Field(default=None, description="Is vertical")
    is_horizontal: bool | None = Field(default=None, description="Is horizontal")
    climbing_type: str | None = Field(default=None, description="Climbing type")
    grade: str | int | None = Field(default=None, description="Grade")
    length: int | None = Field(default=None, description="Length in metres")
    pitches: list[TemplatePitchMCPSchema] = Field(
        default_factory=list, description="Pitches"
    )
    summary: str = Field(description="AI-friendly summary of the template")


class ActivityTemplateListMCPResponse(BaseModel):
    """AI-friendly activity template list response."""

    templates: list[ActivityTemplateMCPResponse] = Field(
        description="List of templates"
    )
    summary: str = Field(description="AI-friendly summary")


class JournalTemplateMCPResponse(BaseModel):
    """The activity template an abseiling-derived journal was created from.

    The reference is durable: ``template`` carries the template's own standard
    pitches, which are independent of (and may differ from) the journal's edited
    pitches.
    """

    journal_id: int = Field(description="Journal id")
    has_template: bool = Field(
        description="Whether the journal references an activity template"
    )
    template: ActivityTemplateMCPResponse | None = Field(
        default=None,
        description="The referenced template incl. its standard pitches, or null",
    )
    summary: str = Field(description="AI-friendly summary")


class GearItemMCPResponse(BaseModel):
    """AI-friendly gear item response."""

    id: str = Field(description="Gear item UUID")
    name: str = Field(description="Gear item name")
    model: str | None = Field(default=None, description="Model name/number")
    serial_number: str | None = Field(default=None, description="Serial number")
    purchase_date: str | None = Field(
        default=None, description="Purchase date (ISO format)"
    )
    manufacturer: str | None = Field(default=None, description="Manufacturer")
    summary: str = Field(description="AI-friendly summary of the gear item")


class GearItemListMCPResponse(BaseModel):
    """AI-friendly gear item list response."""

    gear_items: list[GearItemMCPResponse] = Field(description="List of gear items")
    summary: str = Field(description="AI-friendly summary")


class JournalTagInfo(BaseModel):
    """AI-friendly journal tag information."""

    id: str = Field(description="Journal tag UUID")
    name: str = Field(description="Tag name (unique across journal tags)")
    color: str | None = Field(
        default=None, description="Hex colour code for the tag badge (e.g. #FF0000)"
    )
    description: str | None = Field(
        default=None, description="What the tag is used for, if described"
    )
    parent_id: str | None = Field(
        default=None,
        description="UUID of the parent tag, or null for a root tag",
    )
    created_at: str | None = Field(
        default=None, description="Creation timestamp (ISO format)"
    )


class JournalTagListMCPResponse(BaseModel):
    """AI-friendly journal tag list response."""

    tags: list[JournalTagInfo] = Field(description="Journal tags, ordered by name")
    total_count: int = Field(description="Number of tags returned")
    summary: str = Field(description="AI-friendly summary of the journal tag system")
    suggestions: list[str] = Field(
        default_factory=list, description="Ways to use journal tags"
    )


class IncompleteOutdoorActivityMCPEntry(BaseModel):
    """An outdoor journal flagged by the incomplete review, with its reasons."""

    journal_id: int = Field(description=JOURNAL_ID_DESC)
    title: str = Field(description=JOURNAL_TITLE_DESC)
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    subtypes: list[str] = Field(
        description="Outdoor activity subtypes present on the journal"
    )
    reasons: list[str] = Field(
        description=(
            "Why the journal is flagged: no_attributes (subtype fields all "
            "empty), missing_template (abseiling activity without a template), "
            "no_participants (non-bushwalking activity with no participants)"
        )
    )
    dismissed: bool = Field(
        description=(
            "Whether the journal is dismissed from the review "
            "(only true when listed with include_dismissed)"
        )
    )


class IncompleteOutdoorActivitiesMCPResponse(BaseModel):
    """AI-friendly incomplete outdoor activities list response."""

    total_count: int = Field(description="Number of incomplete activities")
    activities: list[IncompleteOutdoorActivityMCPEntry] = Field(
        description="Incomplete outdoor activities, newest first"
    )
    summary: str = Field(description="AI-friendly summary")


class OutdoorActivityDismissalMCPResponse(BaseModel):
    """AI-friendly dismissal state after a dismiss/undismiss action."""

    journal_id: int = Field(description=JOURNAL_ID_DESC)
    dismissed: bool = Field(
        description="Whether the journal is now dismissed from the incomplete review"
    )
    provenance: str | None = Field(
        default=None, description="Source recorded for the dismissal (e.g. mcp)"
    )
    was_dismissed: bool | None = Field(
        default=None,
        description="On undismiss: whether the journal was dismissed beforehand",
    )
    summary: str = Field(description="AI-friendly summary")


class UpcomingOutdoorActivityMCPEntry(BaseModel):
    """An upcoming outdoor activity or planning event on the dashboard."""

    journal_id: int = Field(description=JOURNAL_ID_DESC)
    title: str = Field(description=JOURNAL_TITLE_DESC)
    event_date_range: EventDateRangeSchema = Field(description=EVENT_DATE_RANGE_DESC)
    subtypes: list[str] = Field(
        description="Outdoor activity subtypes present on the journal"
    )
    is_planning: bool = Field(
        description=(
            "Whether the entry is an OUTDOOR_PLANNING event "
            "rather than an outdoor activity"
        )
    )


class CheckedOutGearMCPEntry(BaseModel):
    """A gear item currently checked out."""

    gear_item_id: str = Field(description="Gear item UUID")
    name: str = Field(description="Gear item name")
    checked_out_since: datetime = Field(
        description="When the item was checked out (resolved checkout date)"
    )
    journal_id: int = Field(description="GEAR_USAGE journal recording the checkout")


class TemplateDoneMCPEntry(BaseModel):
    """A template the user has done, with its per-template done-count.

    The template type is the ``templates_done`` mapping key, so it is not
    repeated here.
    """

    template_id: str = Field(description="Activity template UUID")
    name: str = Field(description="Template name")
    done_count: int = Field(
        description=(
            "How many of the user's abseiling activities reference the template"
        )
    )


class OutdoorDashboardMCPResponse(BaseModel):
    """AI-friendly outdoor dashboard response with all four widget sections."""

    upcoming_activities: list[UpcomingOutdoorActivityMCPEntry] = Field(
        description=(
            "Upcoming outdoor activities and planning events "
            "(next 30 days, soonest first, capped at 10)"
        )
    )
    checked_out_gear: list[CheckedOutGearMCPEntry] = Field(
        description="Gear currently checked out, longest out first"
    )
    activity_totals_last_30_days: dict[str, int] = Field(
        description="Outdoor activity counts by journal type over the last 30 days"
    )
    activity_totals_last_365_days: dict[str, int] = Field(
        description="Outdoor activity counts by journal type over the last 365 days"
    )
    total_activities_last_30_days: int = Field(
        description=(
            "Distinct outdoor activities logged in the last 30 days. Not the sum "
            "of activity_totals_last_30_days: a journal recording two independent "
            "subtypes appears in two type buckets but is one activity."
        )
    )
    total_activities_last_365_days: int = Field(
        description=(
            "Distinct outdoor activities logged in the last 365 days "
            "(not the sum of activity_totals_last_365_days)"
        )
    )
    templates_done: dict[str, list[TemplateDoneMCPEntry]] = Field(
        description=(
            "Unique templates referenced by the user's abseiling activities, "
            "grouped by template type. The done-counts are all-time."
        )
    )
    templates_done_last_30_days: int = Field(
        description=(
            "Distinct templates done in the last 30 days. The templates_done "
            "counts are all-time, so this cannot be derived from them."
        )
    )
    summary: str = Field(description="AI-friendly summary")


def build_dashboard_summary(
    *,
    upcoming_activities: Sequence[UpcomingOutdoorActivityMCPEntry],
    checked_out_gear: Sequence[CheckedOutGearMCPEntry],
    total_last_30_days: int,
    templates_done: Mapping[str, Sequence[TemplateDoneMCPEntry]],
    templates_done_last_30_days: int,
) -> str:
    """The dashboard summary line, counting across the four sections.

    ``total_last_30_days`` and ``templates_done_last_30_days`` come from the
    service's distinct counts — summing the per-type mappings here would
    over-count multi-subtype journals.
    """
    upcoming_count = len(upcoming_activities)
    gear_count = len(checked_out_gear)
    template_count = sum(len(templates) for templates in templates_done.values())
    return (
        f"Dashboard: {upcoming_count} upcoming "
        f"activit{'y' if upcoming_count == 1 else 'ies'}, "
        f"{gear_count} gear item{'' if gear_count == 1 else 's'} checked out, "
        f"{total_last_30_days} "
        f"outdoor activit{'y' if total_last_30_days == 1 else 'ies'} "
        f"in the last 30 days, "
        f"{template_count} unique template{'' if template_count == 1 else 's'} done "
        f"({templates_done_last_30_days} in the last 30 days)."
    )
