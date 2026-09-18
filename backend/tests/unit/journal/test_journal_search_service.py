"""Unit tests for JournalSearchService: filtered search and date-window browsing.

A window's days are the acting user's **local** days, so the bounds the service
hands the repository are instants in the user's configured timezone. The cases
below fix a zone whose offset would give a UTC reading a different answer.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.journal_date_resolver import (
    JournalDateResolver,
    local_date,
)
from app.core.journal.services.journal_search_service import (
    JournalSearchFilters,
    JournalSearchService,
    compute_date_window,
)

ANCHOR = date(2026, 4, 2)
WINDOW_START_ISO = "2026-03-31"
# The window's instants: local midnight on its first day, through the last
# microsecond before the day after its last one begins. UTC here, since the
# default test user has no timezone saved.
WINDOW_RANGE_START_ISO = "2026-03-31T00:00:00+00:00"
WINDOW_END_ISO = "2026-04-06T23:59:59.999999+00:00"


def _date_resolver(timezone: str | None = None) -> JournalDateResolver:
    """A resolver over a settings repository that reports one timezone."""
    user_settings_repo = AsyncMock()
    user_settings_repo.get_timezone.return_value = timezone
    return JournalDateResolver(user_settings_repo=user_settings_repo)


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
    *,
    count: int,
    journals: list[Journal],
    documents: list[dict[str, Any]],
    timezone: str | None = None,
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
        JournalSearchService(
            journal_repo=journal_repo,
            search_service=search_service,
            date_resolver=_date_resolver(timezone),
        ),
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
            "start_date": WINDOW_RANGE_START_ISO,
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
            start_date=WINDOW_RANGE_START_ISO,
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


def _filters(**overrides: Any) -> JournalSearchFilters:
    values: dict[str, Any] = {
        "type_filters": [],
        "source_filter": None,
        "start_date": None,
        "end_date": None,
        "tag_ids": None,
        "contact_id": None,
        "calendar_id": None,
        "parent_id": None,
    }
    values.update(overrides)
    return JournalSearchFilters(**values)


_NO_RELATIONAL_FILTERS: dict[str, Any] = {
    "start_date": None,
    "end_date": None,
    "contact_id": None,
    "tag_ids": None,
    "calendar_id": None,
    "parent_id": None,
}


async def _types_never_read(journal_id: int) -> list[str]:
    raise AssertionError(f"types read for journal {journal_id}")


class TestSearch:
    @pytest.mark.asyncio
    async def test_source_with_no_linked_journals_stops_at_the_source(self) -> None:
        service, journal_repo, search_service = _service(
            count=0, journals=[], documents=[]
        )
        journal_repo.find_ids_by_integration_source.return_value = set()

        outcome = await service.search(
            "user-1",
            query="river",
            filters=_filters(source_filter="strava"),
            limit=20,
            offset=0,
            read_types=_types_never_read,
        )

        assert outcome.source_journal_ids == set()
        assert (outcome.backend, outcome.total_hits) == ("database", 0)
        journal_repo.find_ids_by_integration_source.assert_awaited_once_with(
            "user-1", "strava"
        )
        journal_repo.find_ids_by_filters.assert_not_called()
        search_service.search_journals.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_intersects_the_relational_filters_through_candidate_ids(
        self,
    ) -> None:
        service, journal_repo, search_service = _service(
            count=0, journals=[], documents=[_document(4)]
        )
        journal_repo.find_ids_by_integration_source.return_value = {9, 4}
        journal_repo.find_ids_by_filters.return_value = {4}
        start = datetime(2025, 10, 1, tzinfo=UTC)

        outcome = await service.search(
            "user-1",
            query="  canyon ",
            filters=_filters(
                type_filters=["canyoning"],
                source_filter="strava",
                start_date=start,
                tag_ids=["tag-1"],
                contact_id=12,
            ),
            limit=5,
            offset=10,
            read_types=_types_never_read,
        )

        assert outcome.backend == "meilisearch"
        assert [hit.id for hit in outcome.hits] == [4]
        assert (outcome.total_hits, outcome.processing_time_ms) == (1, 3)
        assert outcome.source_journal_ids == {9, 4}
        journal_repo.find_ids_by_filters.assert_awaited_once_with(
            user_id="user-1",
            journal_ids=[4, 9],
            start_date=start.isoformat(),
            end_date=None,
            contact_id="12",
            tag_ids=["tag-1"],
            calendar_id=None,
            parent_id=None,
        )
        search_service.search_journals.assert_called_once_with(
            query="canyon",
            filters={"user_id": "user-1", "types": ["CANYONING"], "id": [4]},
            limit=5,
            offset=10,
        )

    @pytest.mark.asyncio
    async def test_query_without_filters_searches_everything(self) -> None:
        service, journal_repo, search_service = _service(
            count=0, journals=[], documents=[]
        )

        outcome = await service.search(
            "user-1",
            query="river",
            filters=_filters(),
            limit=20,
            offset=0,
            read_types=_types_never_read,
        )

        assert (outcome.backend, outcome.total_hits, outcome.hits) == (
            "meilisearch",
            0,
            [],
        )
        assert outcome.source_journal_ids is None
        journal_repo.find_ids_by_filters.assert_not_called()
        search_service.search_journals.assert_called_once_with(
            query="river", filters={"user_id": "user-1"}, limit=20, offset=0
        )

    @pytest.mark.asyncio
    async def test_blank_query_lists_one_type_from_the_database(self) -> None:
        journals = [_journal(1)]
        service, journal_repo, search_service = _service(
            count=7, journals=journals, documents=[]
        )
        journal_repo.find_ids_by_integration_source.return_value = {1, 2}

        outcome = await service.search(
            "user-1",
            query="  ",
            filters=_filters(type_filters=["event"], source_filter="google_calendar"),
            limit=1,
            offset=3,
            read_types=_types_never_read,
        )

        assert (outcome.backend, outcome.total_hits) == ("database", 7)
        assert outcome.journals == journals
        assert outcome.journal_types is None
        journal_repo.count_all.assert_awaited_once_with(
            user_id="user-1",
            journal_type="event",
            journal_ids=[1, 2],
            **_NO_RELATIONAL_FILTERS,
        )
        journal_repo.get_all.assert_awaited_once_with(
            user_id="user-1",
            limit=1,
            offset=3,
            journal_type="event",
            journal_ids=[1, 2],
            **_NO_RELATIONAL_FILTERS,
        )
        search_service.search_journals.assert_not_called()

    @pytest.mark.asyncio
    async def test_several_types_are_matched_on_every_candidate_then_paged(
        self,
    ) -> None:
        journals = [_journal(1), _journal(2), _journal(3), _journal(4)]
        service, journal_repo, _ = _service(count=4, journals=journals, documents=[])
        types = {1: ["event"], 2: ["note"], 3: ["mood_rating", "event"], 4: ["travel"]}

        async def read_types(journal_id: int) -> list[str]:
            return types[journal_id]

        outcome = await service.search(
            "user-1",
            query=None,
            filters=_filters(type_filters=["event", "travel"]),
            limit=2,
            offset=1,
            read_types=read_types,
        )

        assert outcome.total_hits == 3
        assert [journal.id for journal in outcome.journals] == [3, 4]
        assert outcome.journal_types == {3: ["mood_rating", "event"], 4: ["travel"]}
        journal_repo.count_all.assert_awaited_once_with(
            user_id="user-1", journal_ids=None, **_NO_RELATIONAL_FILTERS
        )
        journal_repo.get_all.assert_awaited_once_with(
            user_id="user-1",
            limit=4,
            offset=0,
            journal_ids=None,
            **_NO_RELATIONAL_FILTERS,
        )


@pytest.mark.unit
class TestBrowseWindowInTheUsersTimezone:
    """The window's days are the user's local days, not UTC's."""

    @pytest.mark.asyncio
    async def test_the_bounds_are_the_users_local_midnights(self) -> None:
        """Sydney is +10 in June, so its day opens 10 hours before UTC's.

        Asserted on what the repository is asked for, because that is the
        comparison that decides which journals are in the window.
        """
        service, journal_repo, _ = _service(
            count=0, journals=[], documents=[], timezone="Australia/Sydney"
        )

        await service.browse_window(
            "user-1",
            anchor=date(2026, 6, 15),
            days_back=0,
            days_forward=0,
            type_filters=[],
            search=None,
            limit=50,
            offset=0,
        )

        bounds = journal_repo.count_all.await_args.kwargs
        assert bounds["start_date"] == "2026-06-15T00:00:00+10:00"
        assert bounds["end_date"] == "2026-06-15T23:59:59.999999+10:00"

    @pytest.mark.asyncio
    async def test_an_omitted_anchor_is_today_in_the_users_timezone(self) -> None:
        """Kiritimati is +14, so its date differs from UTC's every afternoon.

        Sandwiched between two readings of the clock rather than compared with a
        third: a bare equality would fail whenever the readings landed either
        side of the local midnight.
        """
        service, _, _ = _service(
            count=0, journals=[], documents=[], timezone="Pacific/Kiritimati"
        )
        tz = ZoneInfo("Pacific/Kiritimati")

        before = datetime.now(UTC)
        outcome = await service.browse_window(
            "user-1",
            anchor=None,
            days_back=0,
            days_forward=0,
            type_filters=[],
            search=None,
            limit=50,
            offset=0,
        )
        after = datetime.now(UTC)

        assert local_date(before, tz) <= outcome.anchor <= local_date(after, tz)
        assert outcome.timezone == "Pacific/Kiritimati"

    @pytest.mark.asyncio
    async def test_a_user_with_no_timezone_is_read_in_utc(self) -> None:
        """The fallback, stated where the zone-specific cases are."""
        service, journal_repo, _ = _service(count=0, journals=[], documents=[])

        outcome = await service.browse_window(
            "user-1",
            anchor=ANCHOR,
            days_back=2,
            days_forward=4,
            type_filters=[],
            search=None,
            limit=50,
            offset=0,
        )

        assert outcome.timezone == "UTC"
        assert outcome.anchor == ANCHOR
        assert (
            journal_repo.count_all.await_args.kwargs["start_date"]
            == WINDOW_RANGE_START_ISO
        )
