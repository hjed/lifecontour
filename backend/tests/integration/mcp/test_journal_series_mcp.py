"""Integration tests for MCP journal series tools."""

from datetime import UTC, datetime
from typing import Any, NamedTuple
from uuid import UUID

import pytest
from core_shared.models.journals import EventDateRange, Journal
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.models.journal_series import JournalSeries
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)
from tests.integration.series_merge_seeding import (
    journal_exists,
    member_ids,
    seed_member,
    seed_series,
    series_exists,
)

USER_ID = "test-user-123"


async def _call_tool(
    client: Any, name: str, arguments: dict[str, object]
) -> dict[str, Any]:
    return await call_mcp_tool(client, name, arguments)


async def _seed_journal(
    connection: AsyncConnection, title: str = "Series member"
) -> int:
    journal = await SqlJournalRepository(connection).save(
        Journal(
            user_id=USER_ID,
            title=title,
            content="",
            event_date_range=EventDateRange(
                start=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
                end=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
            ),
        )
    )
    assert journal.id is not None
    return journal.id


async def _seed_series(
    connection: AsyncConnection, name: str = "Physio appointments"
) -> str:
    series = await SqlJournalSeriesRepository(connection).save(
        JournalSeries(user_id=USER_ID, name=name)
    )
    assert series.id is not None
    return str(series.id)


class TestJournalSeriesToolsIntegration:
    """Integration tests for MCP journal series tools with real services."""

    @pytest.mark.asyncio
    async def test_create_series_tool(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "create_series",
                {"name": "Physio appointments", "description": "Weekly physio"},
            )

            assert "error" not in payload
            assert payload["name"] == "Physio appointments"
            assert payload["description"] == "Weekly physio"
            assert payload["auto_created"] is False

            repo = SqlJournalSeriesRepository(clean_database)
            db_series = await repo.find_all(USER_ID)
            assert [s.name for s in db_series] == ["Physio appointments"]

    @pytest.mark.asyncio
    async def test_list_series_tool(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        await _seed_series(clean_database, name="Alpha series")
        await _seed_series(clean_database, name="Zebra series")

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(client, "list_series", {})

            assert "error" not in payload
            names = [s["name"] for s in payload["series"]]
            assert names == ["Alpha series", "Zebra series"]

    @pytest.mark.asyncio
    async def test_get_series_returns_members(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series_id = await _seed_series(clean_database)
        journal_id = await _seed_journal(clean_database, title="Physio session 1")
        await SqlJournalSeriesRepository(clean_database).add_member(
            UUID(series_id), journal_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(client, "get_series", {"series_id": series_id})

            assert "error" not in payload
            assert payload["id"] == series_id
            assert payload["name"] == "Physio appointments"
            members = payload["member_journals"]
            assert len(members) == 1
            assert members[0]["id"] == journal_id
            assert members[0]["title"] == "Physio session 1"

    @pytest.mark.asyncio
    async def test_add_and_remove_journal_from_series_tools(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series_id = await _seed_series(clean_database)
        journal_id = await _seed_journal(clean_database)

        async with authenticated_lifespan_client() as client:
            add_payload = await _call_tool(
                client,
                "add_journal_to_series",
                {"series_id": series_id, "journal_id": journal_id},
            )
            assert "error" not in add_payload

            get_payload = await _call_tool(
                client, "get_series", {"series_id": series_id}
            )
            assert [m["id"] for m in get_payload["member_journals"]] == [journal_id]

            remove_payload = await _call_tool(
                client,
                "remove_journal_from_series",
                {"series_id": series_id, "journal_id": journal_id},
            )
            assert "error" not in remove_payload

            get_payload = await _call_tool(
                client, "get_series", {"series_id": series_id}
            )
            assert get_payload["member_journals"] == []

    @pytest.mark.asyncio
    async def test_update_and_delete_series_tools(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series_id = await _seed_series(clean_database, name="Old name")

        async with authenticated_lifespan_client() as client:
            update_payload = await _call_tool(
                client,
                "update_series",
                {"series_id": series_id, "name": "New name"},
            )
            assert "error" not in update_payload
            assert update_payload["name"] == "New name"

            delete_payload = await _call_tool(
                client, "delete_series", {"series_id": series_id}
            )
            assert "error" not in delete_payload

            repo = SqlJournalSeriesRepository(clean_database)
            assert await repo.find_all(USER_ID) == []

    @pytest.mark.asyncio
    async def test_add_journal_to_unknown_series_errors(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await _seed_journal(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "add_journal_to_series",
                {
                    "series_id": "00000000-0000-0000-0000-000000000042",
                    "journal_id": journal_id,
                },
            )

            assert "error" in payload

    @pytest.mark.asyncio
    async def test_get_journal_includes_series(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series_id = await _seed_series(clean_database)
        journal_id = await _seed_journal(clean_database)
        await SqlJournalSeriesRepository(clean_database).add_member(
            UUID(series_id), journal_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client, "get_journal", {"journal_id": journal_id}
            )

            assert "error" not in payload
            assert payload["series"] == [
                {"id": series_id, "name": "Physio appointments"}
            ]

    @pytest.mark.asyncio
    async def test_update_series_rejects_blank_name(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series_id = await _seed_series(clean_database, name="Keep this name")

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "update_series",
                {"series_id": series_id, "name": "   "},
            )

            assert "error" in payload

        repo = SqlJournalSeriesRepository(clean_database)
        db_series = await repo.find_by_id(UUID(series_id), USER_ID)
        assert db_series is not None
        assert db_series.name == "Keep this name"


class _SameDayPair(NamedTuple):
    source: UUID
    destination: UUID
    source_journal: int
    destination_journal: int


async def _seed_same_day_pair(connection: AsyncConnection) -> _SameDayPair:
    """Two series with one journal each on 3 August, titled differently."""
    source = await seed_series(connection, "Old standup")
    destination = await seed_series(connection, "Standup")
    start = datetime(2026, 8, 3, 9, tzinfo=UTC)
    source_journal = await seed_member(connection, source, title="Old", start=start)
    destination_journal = await seed_member(
        connection, destination, title="New", start=start
    )
    return _SameDayPair(source, destination, source_journal, destination_journal)


def _pairs_arg(source_journal: int, destination_journal: int) -> list[dict[str, int]]:
    return [
        {
            "source_journal_id": source_journal,
            "destination_journal_id": destination_journal,
        }
    ]


async def _call_series_tool(
    client: Any,
    name: str,
    source: UUID,
    destination: UUID,
    **arguments: object,
) -> dict[str, Any]:
    return await _call_tool(
        client,
        name,
        {
            "destination_series_id": str(destination),
            "source_series_id": str(source),
            **arguments,
        },
    )


class TestSeriesMergeToolsIntegration:
    """The series-merge MCP tools behave like their REST counterparts."""

    @pytest.mark.asyncio
    async def test_preview_series_merge_reports_same_day_pairs(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        pair = await _seed_same_day_pair(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await _call_series_tool(
                client,
                "preview_series_merge",
                pair.source,
                pair.destination,
                policies={"title": "skip_if_different"},
            )

        assert "error" not in payload
        assert payload["days"] == [
            {
                "date": "2026-08-03",
                "kind": "skipped",
                "source_journal_ids": [pair.source_journal],
                "destination_journal_ids": [pair.destination_journal],
                "differing_fields": ["title"],
                "skip_reason": "title",
            }
        ]
        assert await series_exists(clean_database, pair.source)

    @pytest.mark.asyncio
    async def test_preview_series_merge_rejects_the_same_series(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series = await seed_series(clean_database, "Standup")

        async with authenticated_lifespan_client() as client:
            payload = await _call_series_tool(
                client, "preview_series_merge", series, series
            )

        assert "error" in payload

    @pytest.mark.asyncio
    async def test_merge_series_merges_confirmed_pairs_and_deletes_the_source(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        pair = await _seed_same_day_pair(clean_database)

        async with authenticated_lifespan_client() as client:
            payload = await _call_series_tool(
                client,
                "merge_series",
                pair.source,
                pair.destination,
                pairs=_pairs_arg(pair.source_journal, pair.destination_journal),
                policies={"title": "source"},
            )

        assert "error" not in payload
        assert [day["kind"] for day in payload["days"]] == ["merged"]
        assert not await series_exists(clean_database, pair.source)
        assert not await journal_exists(clean_database, pair.source_journal)
        assert await member_ids(clean_database, pair.destination) == {
            pair.destination_journal
        }

    @pytest.mark.asyncio
    async def test_merge_series_refuses_a_stale_pair(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        pair = await _seed_same_day_pair(clean_database)

        async with authenticated_lifespan_client() as client:
            # A pair that was never a candidate: a journal paired with itself.
            payload = await _call_series_tool(
                client,
                "merge_series",
                pair.source,
                pair.destination,
                pairs=_pairs_arg(pair.source_journal, pair.source_journal),
            )

        assert "error" in payload
        assert await series_exists(clean_database, pair.source)
        assert await journal_exists(clean_database, pair.source_journal)
