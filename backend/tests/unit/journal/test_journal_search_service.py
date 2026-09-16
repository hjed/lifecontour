"""Unit tests for JournalSearchService date-window browsing."""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.journal_search_service import (
    JournalSearchService,
    compute_date_window,
)

ANCHOR = date(2026, 4, 2)
WINDOW_START_ISO = "2026-03-31"
WINDOW_END_ISO = "2026-04-06T23:59:59+00:00"


def _journal(journal_id: int) -> Journal:
    moment = datetime(2026, 4, 2, 9, tzinfo=UTC)
    return Journal(
        id=journal_id,
        user_id="user-1",
        title=f"Journal {journal_id}",
        content="content",
        event_date_range=EventDateRange(start=moment, end=moment),
    )


def _document(journal_id: int) -> dict[str, Any]:
    return {
        "id": journal_id,
        "title": f"Journal {journal_id}",
        "content": "content",
        "event_date_range_start": "2026-04-02T09:00:00+00:00",
        "event_date_range_end": "2026-04-02T09:00:00+00:00",
        "types": ["NOTE"],
    }


def _service(
    *, count: int, journals: list[Journal], documents: list[dict[str, Any]]
) -> tuple[JournalSearchService, AsyncMock, MagicMock]:
    journal_repo = AsyncMock()
    journal_repo.count_all.return_value = count
    journal_repo.get_all.return_value = journals
    search_service = MagicMock()
    search_service.search_journals.return_value = {
        "hits": documents,
        "estimated_total_hits": len(documents),
        "processing_time_ms": 3,
    }
    return (
        JournalSearchService(journal_repo=journal_repo, search_service=search_service),
        journal_repo,
        search_service,
    )


class TestComputeDateWindow:
    def test_window_spans_back_and_forward_from_the_anchor(self) -> None:
        assert compute_date_window(ANCHOR, 2, 4) == (
            date(2026, 3, 31),
            date(2026, 4, 6),
        )


class TestBrowseWindow:
    @pytest.mark.asyncio
    async def test_lists_a_page_of_the_window_from_the_database(self) -> None:
        journals = [_journal(1), _journal(2)]
        service, journal_repo, search_service = _service(
            count=5, journals=journals, documents=[]
        )

        outcome = await service.browse_window(
            "user-1",
            anchor=ANCHOR,
            days_back=2,
            days_forward=4,
            type_filters=["event"],
            search=None,
            limit=2,
            offset=2,
        )

        assert outcome.window_start == date(2026, 3, 31)
        assert outcome.window_end == date(2026, 4, 6)
        assert outcome.start_iso == WINDOW_START_ISO
        assert outcome.total_count == 5
        assert outcome.searched is False
        assert outcome.journals == journals
        assert outcome.hits == []
        window = {
            "user_id": "user-1",
            "journal_type": "event",
            "start_date": WINDOW_START_ISO,
            "end_date": WINDOW_END_ISO,
        }
        journal_repo.count_all.assert_awaited_once_with(**window)
        journal_repo.get_all.assert_awaited_once_with(limit=2, offset=2, **window)
        search_service.search_journals.assert_not_called()

    @pytest.mark.asyncio
    async def test_several_types_are_not_a_database_type_filter(self) -> None:
        service, journal_repo, _ = _service(count=0, journals=[], documents=[])

        await service.browse_window(
            "user-1",
            anchor=ANCHOR,
            days_back=2,
            days_forward=4,
            type_filters=["event", "note"],
            search=None,
            limit=50,
            offset=0,
        )

        assert journal_repo.count_all.await_args.kwargs["journal_type"] is None

    @pytest.mark.asyncio
    async def test_search_runs_full_text_over_the_windows_journals(self) -> None:
        service, journal_repo, search_service = _service(
            count=3,
            journals=[_journal(1), _journal(2), _journal(3)],
            documents=[_document(3), _document(1)],
        )

        outcome = await service.browse_window(
            "user-1",
            anchor=ANCHOR,
            days_back=2,
            days_forward=4,
            type_filters=["note"],
            search="  river ",
            limit=1,
            offset=1,
        )

        assert outcome.searched is True
        assert outcome.total_count == 2
        assert [hit.id for hit in outcome.hits] == [1]
        assert outcome.journals == []
        journal_repo.get_all.assert_awaited_once_with(
            user_id="user-1",
            limit=3,
            offset=0,
            journal_type="note",
            start_date=WINDOW_START_ISO,
            end_date=WINDOW_END_ISO,
        )
        search_service.search_journals.assert_called_once_with(
            query="river",
            filters={"user_id": "user-1", "types": ["NOTE"], "id": [1, 2, 3]},
            limit=3,
            offset=0,
        )

    @pytest.mark.asyncio
    async def test_blank_search_is_a_database_listing(self) -> None:
        service, _, search_service = _service(count=0, journals=[], documents=[])

        outcome = await service.browse_window(
            "user-1",
            anchor=ANCHOR,
            days_back=0,
            days_forward=0,
            type_filters=[],
            search="   ",
            limit=50,
            offset=0,
        )

        assert outcome.searched is False
        search_service.search_journals.assert_not_called()
