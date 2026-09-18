"""Unit tests for MCP date-window schema and helper logic."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.core.journal.services.journal_search_service import compute_date_window
from app.mcp.domains.journals.schemas import (
    EventDateRangeSchema,
    JournalDateWindowResponse,
    JournalSearchResult,
)


class TestJournalDateWindowResponse:
    """Tests for the JournalDateWindowResponse schema."""

    def test_serializes_with_all_fields(self) -> None:
        response = JournalDateWindowResponse(
            results=[],
            window_start="2026-03-31",
            window_end="2026-04-06",
            anchor_date="2026-04-02",
            total_count=0,
            has_more=False,
            summary="Found 0 journals in window",
        )
        data = response.model_dump()
        assert data["window_start"] == "2026-03-31"
        assert data["window_end"] == "2026-04-06"
        assert data["anchor_date"] == "2026-04-02"
        assert data["total_count"] == 0
        assert data["has_more"] is False
        assert data["results"] == []

    def test_serializes_with_results(self) -> None:
        from datetime import UTC, datetime

        result = JournalSearchResult(
            id=1,
            title="Test",
            content_excerpt="Content...",
            event_date_range=EventDateRangeSchema(
                start=datetime(2026, 4, 2, tzinfo=UTC),
                end=datetime(2026, 4, 2, 23, 59, 59, tzinfo=UTC),
            ),
            types=["note"],
            tags=[],
            highlighted={},
            summary="Journal: Test",
        )
        response = JournalDateWindowResponse(
            results=[result],
            window_start="2026-03-31",
            window_end="2026-04-06",
            anchor_date="2026-04-02",
            total_count=1,
            has_more=False,
            summary="Found 1 journal in window",
        )
        assert len(response.results) == 1
        assert response.results[0].id == 1

    def test_has_more_true_when_paginated(self) -> None:
        response = JournalDateWindowResponse(
            results=[],
            window_start="2026-03-31",
            window_end="2026-04-06",
            anchor_date="2026-04-02",
            total_count=50,
            has_more=True,
            summary="Found 50 journals in window",
        )
        assert response.has_more is True

    def test_rejects_missing_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            JournalDateWindowResponse()  # type: ignore[call-arg]


class TestComputeDateWindow:
    """Tests for the compute_date_window helper function."""

    def test_default_window_from_today(self) -> None:
        """Default: 2 days back, 4 days forward from anchor."""
        anchor = date(2026, 4, 2)
        start, end = compute_date_window(anchor, days_back=2, days_forward=4)
        assert start == date(2026, 3, 31)
        assert end == date(2026, 4, 6)

    def test_custom_window(self) -> None:
        anchor = date(2026, 6, 15)
        start, end = compute_date_window(anchor, days_back=7, days_forward=7)
        assert start == date(2026, 6, 8)
        assert end == date(2026, 6, 22)

    def test_zero_offsets(self) -> None:
        """Zero offsets means window is just the anchor day."""
        anchor = date(2026, 1, 1)
        start, end = compute_date_window(anchor, days_back=0, days_forward=0)
        assert start == anchor
        assert end == anchor

    def test_window_crosses_month_boundary(self) -> None:
        anchor = date(2026, 3, 1)
        start, end = compute_date_window(anchor, days_back=5, days_forward=2)
        assert start == date(2026, 2, 24)
        assert end == date(2026, 3, 3)

    def test_window_crosses_year_boundary(self) -> None:
        anchor = date(2026, 1, 2)
        start, end = compute_date_window(anchor, days_back=5, days_forward=1)
        assert start == date(2025, 12, 28)
        assert end == date(2026, 1, 3)
