"""Data models for summary generation pipeline.

These data structures are shared between the input assembler,
prompt builder, and generator services.
"""

from dataclasses import dataclass


@dataclass
class ActivityStatsBucket:
    """A bucket of historical activity counts for a time period."""

    period_label: str
    event_count: int


@dataclass
class SummaryInput:
    """Assembled input data for AI summary generation."""

    contact_id: int
    contact_name: str
    company: str | None
    job_title: str | None
    recent_notes: list[str]
    recent_journals: list[dict[str, str]]
    relationships: list[str]
    recent_history: list[str]
    important_dates: list[str]
    previous_summary: str | None
    activity_stats: list[ActivityStatsBucket]
