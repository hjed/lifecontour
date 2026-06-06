"""Data models for daily summary generation pipeline.

Defines the input contract for assembling journal data for a single day
into a structured format suitable for AI prompt building.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class DailySummaryJournalEntry:
    """A single journal's data prepared for the summary prompt."""

    title: str
    content: str
    types: list[str] = field(default_factory=list)
    contact_names: list[str] = field(default_factory=list)
    mood_value: int | None = None
    energy_level: int | None = None


@dataclass
class DailySummaryInput:
    """Data assembled for daily summary generation."""

    user_id: str
    summary_date: date
    journals: list[DailySummaryJournalEntry] = field(default_factory=list)
    journal_count: int = 0
    event_count: int = 0
    contact_names: list[str] = field(default_factory=list)
    mood_values: list[int] = field(default_factory=list)
    previous_summary: str | None = None
    timezone: str = "UTC"
