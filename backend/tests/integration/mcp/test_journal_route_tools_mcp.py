"""Integration tests for the MCP journal route (GPX track) tools."""

import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.mcp.http_helpers import call_mcp_tool, initialize_mcp_session
from tests.integration.tasks.task_seeding import OTHER_USER_ID, create_journal

VALID_GPX = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
    "<trk><name>Harbour Loop</name><trkseg>"
    '<trkpt lat="-33.8568" lon="151.2153"><ele>5</ele></trkpt>'
    '<trkpt lat="-33.8570" lon="151.2160"><ele>6</ele></trkpt>'
    "</trkseg></trk></gpx>"
)


def _large_gpx(target_bytes: int) -> str:
    """A well-formed GPX track of roughly ``target_bytes`` bytes."""
    point = (
        '<trkpt lat="-33.856812" lon="151.215312"><ele>12.4</ele>'
        "<time>2024-06-01T00:00:00Z</time></trkpt>"
    )
    head = '<?xml version="1.0"?><gpx version="1.1" creator="test"><trk><trkseg>'
    tail = "</trkseg></trk></gpx>"
    count = (target_bytes - len(head) - len(tail)) // len(point) + 1
    return head + point * count + tail


async def _route_rows(connection: AsyncConnection, journal_id: int) -> list[Any]:
    result = await connection.execute(
        text(
            "SELECT id, name, description, gpx_data FROM routes "
            "WHERE journal_id = :journal_id ORDER BY created_at"
        ),
        {"journal_id": journal_id},
    )
    return list(result.fetchall())


async def _route_event_payloads(
    connection: AsyncConnection, event_type: str
) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            "SELECT event_data FROM outbox_events "
            "WHERE event_type = :event_type ORDER BY id"
        ),
        {"event_type": event_type},
    )
    return [json.loads(row.event_data) for row in result.fetchall()]


async def _call(client: Any, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = await initialize_mcp_session(client)
    return await call_mcp_tool(client, session_id, tool, arguments)


class TestCreateJournalRoute:
    @pytest.mark.asyncio
    async def test_attaches_a_gpx_route_with_mcp_provenance(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "create_journal_route",
                {
                    "journal_id": journal_id,
                    "name": "Harbour Loop",
                    "description": "Morning paddle",
                    "gpx_data": VALID_GPX,
                },
            )

        assert "error" not in payload, payload
        assert payload["journal_id"] == journal_id
        assert payload["name"] == "Harbour Loop"
        assert payload["description"] == "Morning paddle"
        assert payload["has_gpx_data"] is True
        assert payload["gpx_size_bytes"] == len(VALID_GPX.encode())
        assert "gpx_data" not in payload

        rows = await _route_rows(clean_database, journal_id)
        assert [(str(r.id), r.name, r.gpx_data) for r in rows] == [
            (payload["id"], "Harbour Loop", VALID_GPX)
        ]

        events = await _route_event_payloads(clean_database, "RouteCreated")
        assert len(events) == 1
        assert events[0]["route_id"] == payload["id"]
        assert events[0]["source"] == "mcp"
        assert events[0]["changed_by"] == "mcp"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gpx_data", ["this is not xml", "<kml><Document/></kml>"])
    async def test_invalid_gpx_is_refused_on_gpx_data_and_nothing_is_written(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        gpx_data: str,
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "create_journal_route",
                {"journal_id": journal_id, "name": "Broken", "gpx_data": gpx_data},
            )

        assert payload["error"] == "Validation error"
        assert payload["field"] == "gpx_data"
        assert await _route_rows(clean_database, journal_id) == []
        assert await _route_event_payloads(clean_database, "RouteCreated") == []

    @pytest.mark.asyncio
    async def test_another_users_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(
            SqlJournalRepository(clean_database), user_id=OTHER_USER_ID
        )

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "create_journal_route",
                {"journal_id": journal_id, "name": "Theirs", "gpx_data": VALID_GPX},
            )

        assert payload["error"] == "Journal not found"
        assert await _route_rows(clean_database, journal_id) == []

    @pytest.mark.asyncio
    async def test_accepts_a_multi_megabyte_track(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        gpx_data = _large_gpx(3_600_000)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "create_journal_route",
                {"journal_id": journal_id, "name": "Long day", "gpx_data": gpx_data},
            )

        assert "error" not in payload, payload
        assert payload["gpx_size_bytes"] == len(gpx_data.encode())
        rows = await _route_rows(clean_database, journal_id)
        assert len(rows) == 1
        assert rows[0].gpx_data == gpx_data


class TestListJournalRoutes:
    @pytest.mark.asyncio
    async def test_lists_route_summaries_without_gpx_bodies(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            for name, gpx_data in [
                ("Harbour Loop", VALID_GPX),
                ("Headland Walk", None),
                ("Harbour Return", VALID_GPX),
            ]:
                arguments: dict[str, Any] = {"journal_id": journal_id, "name": name}
                if gpx_data is not None:
                    arguments["gpx_data"] = gpx_data
                created = await call_mcp_tool(
                    client, session_id, "create_journal_route", arguments
                )
                assert "error" not in created, created

            everything = await call_mcp_tool(
                client, session_id, "list_journal_routes", {"journal_id": journal_id}
            )
            harbour_page = await call_mcp_tool(
                client,
                session_id,
                "list_journal_routes",
                {"journal_id": journal_id, "name": "harbour", "limit": 1, "offset": 1},
            )

        assert everything["total_count"] == 3
        assert [r["name"] for r in everything["routes"]] == [
            "Harbour Loop",
            "Headland Walk",
            "Harbour Return",
        ]
        assert [r["has_gpx_data"] for r in everything["routes"]] == [True, False, True]
        assert all("gpx_data" not in r for r in everything["routes"])

        assert harbour_page["total_count"] == 2
        assert [r["name"] for r in harbour_page["routes"]] == ["Harbour Return"]

    @pytest.mark.asyncio
    async def test_another_users_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(
            SqlJournalRepository(clean_database), user_id=OTHER_USER_ID
        )

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client, "list_journal_routes", {"journal_id": journal_id}
            )

        assert payload["error"] == "Journal not found"
