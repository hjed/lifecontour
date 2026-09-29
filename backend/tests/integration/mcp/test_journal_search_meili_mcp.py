"""MCP ``search_journals`` / ``browse_journals_by_date_window`` via MeiliSearch.

The MCP search used to be a single ``ILIKE '%<whole phrase>%'`` over the
journal text, so a multi-word query that was not a literal substring ("Zion
canyoning") silently returned nothing. With a query, the tools now go through
the same ``SearchService.search_journals`` the REST ``/journals/search``
endpoint uses. These tests index real journals into the test MeiliSearch and
exercise the mounted tools end to end.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.search_service import SearchService
from tests.integration.contact_seeding import seed_contact
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

USER_ID = "test-user-123"


async def _insert_journal(
    conn: AsyncConnection,
    *,
    title: str,
    content: str,
    start: datetime,
    strava_activity_id: str | None = None,
    parent_id: int | None = None,
) -> int:
    result = await conn.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content, event_date_range_start,
                 event_date_range_end, parent_id)
            VALUES (:user_id, :title, :content, :start, :end, :parent_id)
            RETURNING id
        """),
        {
            "user_id": USER_ID,
            "title": title,
            "content": content,
            "start": start,
            "end": start + timedelta(hours=2),
            "parent_id": parent_id,
        },
    )
    row = result.fetchone()
    assert row is not None
    journal_id = int(row[0])
    if strava_activity_id is not None:
        await conn.execute(
            text("""
                INSERT INTO journal_fitness_data (journal_id, strava_activity_id)
                VALUES (:journal_id, :strava_activity_id)
            """),
            {"journal_id": journal_id, "strava_activity_id": strava_activity_id},
        )
    return journal_id


@pytest_asyncio.fixture
async def zion_journals(
    clean_database: AsyncConnection, index_journal
) -> dict[str, int]:
    """Two October-2025 journals plus one unrelated; the Zion one is on Strava."""
    echo_id = await _insert_journal(
        clean_database,
        title="Echo Canyon — Zion",
        content="Nice little canyon, but with a Kanangra-grade walkout. "
        "A classic Zion canyoning day.",
        start=datetime(2025, 10, 13, 15, tzinfo=UTC),
        strava_activity_id="16135",
    )
    drive_id = await _insert_journal(
        clean_database,
        title="Zion Drive — Moab → Zion",
        content="Long drive; no canyoning because of the thunderstorm.",
        start=datetime(2025, 10, 12, 6, tzinfo=UTC),
    )
    other_id = await _insert_journal(
        clean_database,
        title="Morning run",
        content="Easy aerobic run along the river.",
        start=datetime(2025, 3, 2, 6, tzinfo=UTC),
    )
    for journal_id in (echo_id, drive_id, other_id):
        await index_journal(journal_id)
    return {"echo": echo_id, "drive": drive_id, "other": other_id}


@pytest.mark.integration
@pytest.mark.meilisearch
class TestSearchJournalsViaMeili:
    @pytest.mark.asyncio
    async def test_multi_word_query_matches_words_not_substring(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"query": "Zion canyoning"}
            )

        assert "error" not in payload, payload
        ids = [r["id"] for r in payload["results"]]
        assert zion_journals["echo"] in ids
        assert zion_journals["drive"] in ids
        assert zion_journals["other"] not in ids
        assert payload["total_hits"] == 2
        echo = next(r for r in payload["results"] if r["id"] == zion_journals["echo"])
        assert echo["title"] == "Echo Canyon — Zion"
        assert "<mark>" in echo["highlighted"]["title"]

    @pytest.mark.asyncio
    async def test_integration_source_filter_intersects_with_query(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Zion", "integration_source": "strava"},
            )

        assert "error" not in payload, payload
        assert [r["id"] for r in payload["results"]] == [zion_journals["echo"]]
        assert payload["summary"] == "Found 1 journal(s) linked to strava"

    @pytest.mark.asyncio
    async def test_in_window_search_uses_word_matching(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {
                    "anchor_date": "2025-10-13",
                    "days_back": 2,
                    "days_forward": 2,
                    "search": "canyoning Zion",
                },
            )

        assert "error" not in payload, payload
        assert {r["id"] for r in payload["results"]} == {
            zion_journals["echo"],
            zion_journals["drive"],
        }
        assert payload["total_count"] == 2

    @pytest.mark.asyncio
    async def test_in_window_search_with_empty_window_is_empty_not_an_error(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {"anchor_date": "2024-01-01", "search": "Zion"},
            )

        assert "error" not in payload, payload
        assert payload["results"] == []
        assert payload["total_count"] == 0
        assert payload["diagnostics"]["journals_for_user_total"] == 3

    @pytest.mark.asyncio
    async def test_meilisearch_failure_is_an_explicit_error_not_empty(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        def boom(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise MeilisearchError("connection refused")

        async with authenticated_lifespan_client() as client:
            with patch.object(SearchService, "search_journals", boom):
                payload = await call_mcp_tool(
                    client, "search_journals", {"query": "Zion"}
                )

        assert payload["error"] == "Search unavailable"
        assert "MeiliSearch" in payload["message"]
        assert "NOT an empty result" in payload["hint"]
        assert "results" not in payload

    @pytest.mark.asyncio
    async def test_no_query_lists_from_database(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        """Listing by source alone does not need the search index."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"integration_source": "strava"}
            )

        assert "error" not in payload, payload
        assert [r["id"] for r in payload["results"]] == [zion_journals["echo"]]


@pytest.mark.integration
@pytest.mark.meilisearch
class TestZeroResultDiagnostics:
    """An empty result says what was searched and what exists regardless."""

    @pytest.mark.asyncio
    async def test_search_with_no_hits_explains_itself(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        index_journal,
    ) -> None:
        journal_id = await _insert_journal(
            clean_database,
            title="Echo Canyon — Zion",
            content="Classic Zion canyoning day.",
            start=datetime(2025, 10, 13, 15, tzinfo=UTC),
            strava_activity_id="16135",
        )
        await index_journal(journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Kanangra", "integration_source": "strava"},
            )
            hit = await call_mcp_tool(client, "search_journals", {"query": "Zion"})

        assert payload["total_hits"] == 0
        diagnostics = payload["diagnostics"]
        assert diagnostics["search_backend"] == "meilisearch"
        assert diagnostics["journals_for_user_total"] == 1
        assert diagnostics["journals_linked_to_source"] == 1
        assert diagnostics["filters"] == {
            "query": "Kanangra",
            "integration_source": "strava",
        }
        assert any("fewer or different words" in s for s in diagnostics["suggestions"])
        assert hit["diagnostics"] is None

    @pytest.mark.asyncio
    async def test_source_with_no_links_says_so(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        await _insert_journal(
            clean_database,
            title="Plain note",
            content="No integrations here.",
            start=datetime(2025, 10, 13, 15, tzinfo=UTC),
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"integration_source": "immich_album"},
            )

        assert payload["total_hits"] == 0
        diagnostics = payload["diagnostics"]
        assert diagnostics["search_backend"] == "database"
        assert diagnostics["journals_for_user_total"] == 1
        assert diagnostics["journals_linked_to_source"] == 0
        assert "No journal is linked to immich_album" in diagnostics["suggestions"][0]

    @pytest.mark.asyncio
    async def test_empty_date_window_explains_itself(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        await _insert_journal(
            clean_database,
            title="Echo Canyon — Zion",
            content="Classic Zion canyoning day.",
            start=datetime(2025, 10, 13, 15, tzinfo=UTC),
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "browse_journals_by_date_window",
                {"anchor_date": "2025-09-04", "days_back": 5, "days_forward": 5},
            )

        assert payload["total_count"] == 0
        diagnostics = payload["diagnostics"]
        assert diagnostics["search_backend"] == "database"
        assert diagnostics["journals_for_user_total"] == 1
        assert diagnostics["filters"] == {
            "window_start": "2025-08-30",
            "window_end": "2025-09-09",
            "timezone": "UTC",
        }
        assert any("Widen the window" in s for s in diagnostics["suggestions"])


@pytest.mark.integration
@pytest.mark.meilisearch
class TestNoteFilterMeansUntyped:
    """``types=NOTE`` means "no typed rows" on both the Meili and SQL paths."""

    @pytest.mark.asyncio
    async def test_note_filter_excludes_typed_journals(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        index_journal,
    ) -> None:
        typed_id = await _insert_journal(
            clean_database,
            title="Echo Canyon — Zion",
            content="Zion canyoning day.",
            start=datetime(2025, 10, 13, 15, tzinfo=UTC),
            strava_activity_id="16135",
        )
        note_id = await _insert_journal(
            clean_database,
            title="Zion Drive",
            content="Plain note about Zion.",
            start=datetime(2025, 10, 12, 6, tzinfo=UTC),
        )
        await index_journal(typed_id)
        await index_journal(note_id)

        async with authenticated_lifespan_client() as client:
            with_query = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Zion", "types": "note"},
            )
            without_query = await call_mcp_tool(
                client, "search_journals", {"types": "note"}
            )

        assert [r["id"] for r in with_query["results"]] == [note_id]
        assert [r["id"] for r in without_query["results"]] == [note_id]


async def _insert_tag(conn: AsyncConnection, name: str, parent_id: Any = None) -> Any:
    result = await conn.execute(
        text("""
            INSERT INTO journal_tags (name, color, parent_id)
            VALUES (:name, '#FF0000', :parent_id)
            RETURNING id
        """),
        {"name": name, "parent_id": parent_id},
    )
    row = result.fetchone()
    assert row is not None
    return row[0]


async def _tag_journal(conn: AsyncConnection, journal_id: int, tag_id: Any) -> None:
    await conn.execute(
        text("""
            INSERT INTO journal_tag_assignments (journal_id, tag_id)
            VALUES (:journal_id, :tag_id)
        """),
        {"journal_id": journal_id, "tag_id": tag_id},
    )


async def _link_contact(
    conn: AsyncConnection, journal_id: int, contact_id: int
) -> None:
    """Seed contact ``contact_id`` and link it to the journal — once per id."""
    await seed_contact(
        conn, first_name="Dana", last_name="Scully", contact_id=contact_id
    )
    await conn.execute(
        text("""
            INSERT INTO journal_contact_relationships (
                journal_id, contact_id, relationship_type
            )
            VALUES (:journal_id, :contact_id, 'PARTICIPANT')
        """),
        {"journal_id": journal_id, "contact_id": contact_id},
    )


@pytest.mark.integration
@pytest.mark.meilisearch
class TestSearchJournalsRelationalFilters:
    """The REST list filters — dates, tags, contact, calendar, parent, paging.

    Each has to narrow both backends identically: the database listing when
    there is no ``query``, and the MeiliSearch query when there is one.
    """

    @pytest.mark.asyncio
    async def test_date_window_narrows_the_database_listing(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"start_date": "2025-10-13", "end_date": "2025-10-13"},
            )

        assert "error" not in payload, payload
        assert [r["id"] for r in payload["results"]] == [zion_journals["echo"]]
        assert payload["total_hits"] == 1

    @pytest.mark.asyncio
    async def test_date_window_narrows_a_meilisearch_query(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        """Both Zion journals match the text; only one is inside the window."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {
                    "query": "Zion canyoning",
                    "start_date": "2025-10-13",
                    "end_date": "2025-10-14",
                },
            )

        assert "error" not in payload, payload
        assert [r["id"] for r in payload["results"]] == [zion_journals["echo"]]
        assert payload["total_hits"] == 1

    @pytest.mark.asyncio
    async def test_date_filter_and_integration_source_intersect(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        """Two id sets AND together rather than one overwriting the other."""
        async with authenticated_lifespan_client() as client:
            inside = await call_mcp_tool(
                client,
                "search_journals",
                {
                    "query": "Zion",
                    "integration_source": "strava",
                    "start_date": "2025-10-13",
                },
            )
            outside = await call_mcp_tool(
                client,
                "search_journals",
                {
                    "query": "Zion",
                    "integration_source": "strava",
                    "end_date": "2025-10-12",
                },
            )

        assert [r["id"] for r in inside["results"]] == [zion_journals["echo"]]
        assert outside["total_hits"] == 0

    @pytest.mark.asyncio
    async def test_tag_name_filter_narrows_both_backends(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        zion_journals: dict[str, int],
    ) -> None:
        """A tag can be named rather than looked up as a UUID first."""
        tag_id = await _insert_tag(clean_database, "canyoning-trips")
        await _tag_journal(clean_database, zion_journals["echo"], tag_id)

        async with authenticated_lifespan_client() as client:
            with_query = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Zion", "tags": "canyoning-trips"},
            )
            without_query = await call_mcp_tool(
                client, "search_journals", {"tags": "Canyoning-Trips"}
            )
            by_id = await call_mcp_tool(
                client, "search_journals", {"tags": str(tag_id)}
            )

        assert [r["id"] for r in with_query["results"]] == [zion_journals["echo"]]
        assert [r["id"] for r in without_query["results"]] == [zion_journals["echo"]]
        assert [r["id"] for r in by_id["results"]] == [zion_journals["echo"]]

    @pytest.mark.asyncio
    async def test_parent_tag_filter_includes_descendant_tags(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        zion_journals: dict[str, int],
    ) -> None:
        parent_tag = await _insert_tag(clean_database, "outdoors")
        child_tag = await _insert_tag(clean_database, "canyoning", parent_id=parent_tag)
        await _tag_journal(clean_database, zion_journals["echo"], child_tag)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"tags": "outdoors"}
            )

        assert [r["id"] for r in payload["results"]] == [zion_journals["echo"]]

    @pytest.mark.asyncio
    async def test_unknown_tag_name_is_an_error_not_an_empty_result(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"tags": "no-such-tag"}
            )

        assert "error" in payload, payload
        assert "no-such-tag" in payload["message"]

    @pytest.mark.asyncio
    async def test_contact_filter_narrows_both_backends(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        zion_journals: dict[str, int],
    ) -> None:
        await _link_contact(clean_database, zion_journals["drive"], 7001)

        async with authenticated_lifespan_client() as client:
            with_query = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Zion", "contact_id": 7001},
            )
            without_query = await call_mcp_tool(
                client, "search_journals", {"contact_id": 7001}
            )

        assert [r["id"] for r in with_query["results"]] == [zion_journals["drive"]]
        assert [r["id"] for r in without_query["results"]] == [zion_journals["drive"]]

    @pytest.mark.asyncio
    async def test_parent_filter_returns_only_children(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        index_journal,
    ) -> None:
        trip_id = await _insert_journal(
            clean_database,
            title="Zion trip",
            content="The whole trip.",
            start=datetime(2025, 10, 12, 6, tzinfo=UTC),
        )
        child_id = await _insert_journal(
            clean_database,
            title="Zion day two",
            content="Echo Canyon.",
            start=datetime(2025, 10, 13, 15, tzinfo=UTC),
            parent_id=trip_id,
        )
        for journal_id in (trip_id, child_id):
            await index_journal(journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"parent_id": trip_id}
            )
            with_query = await call_mcp_tool(
                client,
                "search_journals",
                {"query": "Zion", "parent_id": trip_id},
            )

        assert [r["id"] for r in payload["results"]] == [child_id]
        assert [r["id"] for r in with_query["results"]] == [child_id]

    @pytest.mark.asyncio
    async def test_calendar_filter_narrows_the_listing(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        zion_journals: dict[str, int],
    ) -> None:
        result = await clean_database.execute(
            text("""
                INSERT INTO calendars (user_id, name, color)
                VALUES (:user_id, 'Trips', '#00FF00')
                RETURNING id
            """),
            {"user_id": USER_ID},
        )
        row = result.fetchone()
        assert row is not None
        calendar_id = row[0]
        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
                VALUES (:journal_id, :calendar_id, true)
            """),
            {"journal_id": zion_journals["drive"], "calendar_id": calendar_id},
        )

        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"calendar_id": str(calendar_id)},
            )

        assert [r["id"] for r in payload["results"]] == [zion_journals["drive"]]

    @pytest.mark.asyncio
    async def test_offset_pages_the_database_listing(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            first = await call_mcp_tool(client, "search_journals", {"limit": 1})
            second = await call_mcp_tool(
                client, "search_journals", {"limit": 1, "offset": 1}
            )

        assert first["total_hits"] == 3
        assert second["total_hits"] == 3
        assert [r["id"] for r in first["results"]] == [zion_journals["echo"]]
        assert [r["id"] for r in second["results"]] == [zion_journals["drive"]]

    @pytest.mark.asyncio
    async def test_filters_matching_nothing_report_the_filters_back(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        """An empty result names every filter that produced it."""
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client,
                "search_journals",
                {"start_date": "2030-01-01", "end_date": "2030-01-02"},
            )

        assert payload["total_hits"] == 0
        diagnostics = payload["diagnostics"]
        assert diagnostics["search_backend"] == "database"
        assert diagnostics["journals_for_user_total"] == 3
        assert diagnostics["filters"]["start_date"] == "2030-01-01"
        assert diagnostics["filters"]["end_date"] == "2030-01-02"

    @pytest.mark.asyncio
    async def test_invalid_date_filter_is_a_clear_error(
        self, authenticated_lifespan_client, zion_journals: dict[str, int]
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await call_mcp_tool(
                client, "search_journals", {"start_date": "last tuesday"}
            )

        assert "error" in payload, payload
        assert "start_date" in payload["message"]
