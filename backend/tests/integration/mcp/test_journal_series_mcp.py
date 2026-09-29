"""Integration tests for MCP journal series tools."""

from datetime import UTC, datetime
from typing import Any
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


class TestSeriesMergeToolsIntegration:
    """The series-merge MCP tools behave like their REST counterparts."""

    @pytest.mark.asyncio
    async def test_preview_series_merge_reports_same_day_pairs(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        source = await seed_series(clean_database, "Old standup")
        destination = await seed_series(clean_database, "Standup")
        source_journal = await seed_member(
            clean_database,
            source,
            title="Old",
            start=datetime(2026, 8, 3, 9, tzinfo=UTC),
        )
        destination_journal = await seed_member(
            clean_database,
            destination,
            title="New",
            start=datetime(2026, 8, 3, 9, tzinfo=UTC),
        )

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "preview_series_merge",
                {
                    "destination_series_id": str(destination),
                    "source_series_id": str(source),
                    "policies": {"title": "skip_if_different"},
                },
            )

        assert "error" not in payload
        assert payload["days"] == [
            {
                "date": "2026-08-03",
                "kind": "skipped",
                "source_journal_ids": [source_journal],
                "destination_journal_ids": [destination_journal],
                "differing_fields": ["title"],
                "skip_reason": "title",
            }
        ]
        assert await series_exists(clean_database, source)

    @pytest.mark.asyncio
    async def test_preview_series_merge_rejects_the_same_series(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        series = await seed_series(clean_database, "Standup")

        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "preview_series_merge",
                {
                    "destination_series_id": str(series),
                    "source_series_id": str(series),
                },
            )

        assert "error" in payload
