"""Integration tests for the MCP journal route (GPX track) tools."""

import json
from typing import Any
from uuid import uuid4

import pytest
from core_shared.models import Route
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)
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
    return await call_mcp_tool(client, tool, arguments)


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
            for name, gpx_data in [
                ("Harbour Loop", VALID_GPX),
                ("Headland Walk", None),
                ("Harbour Return", VALID_GPX),
            ]:
                arguments: dict[str, Any] = {"journal_id": journal_id, "name": name}
                if gpx_data is not None:
                    arguments["gpx_data"] = gpx_data
                created = await call_mcp_tool(client, "create_journal_route", arguments)
                assert "error" not in created, created

            everything = await call_mcp_tool(
                client, "list_journal_routes", {"journal_id": journal_id}
            )
            harbour_page = await call_mcp_tool(
                client,
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


OTHER_GPX = VALID_GPX.replace("Harbour Loop", "Harbour Loop (resurveyed)")


async def _seed_route(
    connection: AsyncConnection,
    journal_id: int,
    *,
    name: str = "Harbour Loop",
    description: str | None = "Morning paddle",
    gpx_data: str | None = VALID_GPX,
) -> str:
    route = await SqlRouteRepository(connection).save(
        Route(
            journal_id=journal_id,
            name=name,
            description=description,
            gpx_data=gpx_data,
        )
    )
    return str(route.id)


class TestUpdateJournalRoute:
    @pytest.mark.asyncio
    async def test_updates_every_field_with_mcp_provenance(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {
                    "journal_id": journal_id,
                    "route_id": route_id,
                    "name": "Harbour Circuit",
                    "description": "Evening paddle",
                    "gpx_data": OTHER_GPX,
                },
            )

        assert "error" not in payload, payload
        assert payload["id"] == route_id
        assert payload["name"] == "Harbour Circuit"
        assert payload["gpx_size_bytes"] == len(OTHER_GPX.encode())

        rows = await _route_rows(clean_database, journal_id)
        assert [(r.name, r.description, r.gpx_data) for r in rows] == [
            ("Harbour Circuit", "Evening paddle", OTHER_GPX)
        ]

        events = await _route_event_payloads(clean_database, "RouteUpdated")
        assert len(events) == 1
        assert events[0]["route_id"] == route_id
        assert events[0]["changed_fields"] == {
            "name": ["Harbour Loop", "Harbour Circuit"],
            "description": ["Morning paddle", "Evening paddle"],
            "gpx_data": ["present", "present"],
        }
        assert events[0]["source"] == "mcp"
        assert events[0]["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_omitted_arguments_are_kept_and_empty_strings_clear(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            renamed = await call_mcp_tool(
                client,
                "update_journal_route",
                {"journal_id": journal_id, "route_id": route_id, "name": "Renamed"},
            )
            rows_after_rename = await _route_rows(clean_database, journal_id)
            cleared = await call_mcp_tool(
                client,
                "update_journal_route",
                {
                    "journal_id": journal_id,
                    "route_id": route_id,
                    "description": "",
                    "gpx_data": "",
                },
            )

        assert "error" not in renamed, renamed
        assert [(r.name, r.description, r.gpx_data) for r in rows_after_rename] == [
            ("Renamed", "Morning paddle", VALID_GPX)
        ]
        assert "error" not in cleared, cleared
        assert cleared["has_gpx_data"] is False
        rows = await _route_rows(clean_database, journal_id)
        assert [(r.name, r.description, r.gpx_data) for r in rows] == [
            ("Renamed", None, None)
        ]

    @pytest.mark.asyncio
    async def test_invalid_gpx_is_refused_and_the_route_is_unchanged(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {
                    "journal_id": journal_id,
                    "route_id": route_id,
                    "name": "Should not stick",
                    "gpx_data": "<kml><Document/></kml>",
                },
            )

        assert payload["error"] == "Validation error"
        assert payload["field"] == "gpx_data"
        rows = await _route_rows(clean_database, journal_id)
        assert [(r.name, r.gpx_data) for r in rows] == [("Harbour Loop", VALID_GPX)]
        assert await _route_event_payloads(clean_database, "RouteUpdated") == []

    @pytest.mark.asyncio
    async def test_a_route_on_another_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_repository = SqlJournalRepository(clean_database)
        route_journal_id = await create_journal(journal_repository, title="Paddle")
        other_journal_id = await create_journal(journal_repository, title="Walk")
        route_id = await _seed_route(clean_database, route_journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {"journal_id": other_journal_id, "route_id": route_id, "name": "X"},
            )

        assert payload["error"] == "Route not found"
        rows = await _route_rows(clean_database, route_journal_id)
        assert [r.name for r in rows] == ["Harbour Loop"]

    @pytest.mark.asyncio
    async def test_another_users_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(
            SqlJournalRepository(clean_database), user_id=OTHER_USER_ID
        )
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {"journal_id": journal_id, "route_id": route_id, "name": "Mine now"},
            )

        assert payload["error"] == "Journal not found"
        rows = await _route_rows(clean_database, journal_id)
        assert [r.name for r in rows] == ["Harbour Loop"]

    @pytest.mark.asyncio
    async def test_a_malformed_route_id_names_the_route_id_field(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {"journal_id": journal_id, "route_id": "not-a-uuid", "name": "X"},
            )

        assert payload["error"] == "Validation error"
        assert payload["field"] == "route_id"

    @pytest.mark.asyncio
    async def test_an_identical_update_records_nothing(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {
                    "journal_id": journal_id,
                    "route_id": route_id,
                    "name": "Harbour Loop",
                    "description": "Morning paddle",
                    "gpx_data": VALID_GPX,
                },
            )

        assert "error" not in payload, payload
        assert payload["name"] == "Harbour Loop"
        assert await _route_event_payloads(clean_database, "RouteUpdated") == []

    @pytest.mark.asyncio
    async def test_a_rename_leaves_a_legacy_blank_track_alone(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id, gpx_data="   ")

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "update_journal_route",
                {"journal_id": journal_id, "route_id": route_id, "name": "Renamed"},
            )

        assert "error" not in payload, payload
        rows = await _route_rows(clean_database, journal_id)
        assert [(r.name, r.gpx_data) for r in rows] == [("Renamed", "   ")]
        events = await _route_event_payloads(clean_database, "RouteUpdated")
        assert [e["changed_fields"] for e in events] == [
            {"name": ["Harbour Loop", "Renamed"]}
        ]


class TestDeleteJournalRoute:
    @pytest.mark.asyncio
    async def test_deletes_the_route_with_mcp_provenance(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))
        route_id = await _seed_route(clean_database, journal_id)
        kept_route_id = await _seed_route(clean_database, journal_id, name="Kept")

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "delete_journal_route",
                {"journal_id": journal_id, "route_id": route_id},
            )

        assert payload == {
            "deleted": True,
            "route_id": route_id,
            "journal_id": journal_id,
        }
        rows = await _route_rows(clean_database, journal_id)
        assert [str(r.id) for r in rows] == [kept_route_id]

        events = await _route_event_payloads(clean_database, "RouteDeleted")
        assert len(events) == 1
        assert events[0]["route_id"] == route_id
        assert events[0]["source"] == "mcp"
        assert events[0]["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_a_route_on_another_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_repository = SqlJournalRepository(clean_database)
        route_journal_id = await create_journal(journal_repository, title="Paddle")
        other_journal_id = await create_journal(journal_repository, title="Walk")
        route_id = await _seed_route(clean_database, route_journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "delete_journal_route",
                {"journal_id": other_journal_id, "route_id": route_id},
            )

        assert payload["error"] == "Route not found"
        assert len(await _route_rows(clean_database, route_journal_id)) == 1

    @pytest.mark.asyncio
    async def test_another_users_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(
            SqlJournalRepository(clean_database), user_id=OTHER_USER_ID
        )
        route_id = await _seed_route(clean_database, journal_id)

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "delete_journal_route",
                {"journal_id": journal_id, "route_id": route_id},
            )

        assert payload["error"] == "Journal not found"
        assert len(await _route_rows(clean_database, journal_id)) == 1

    @pytest.mark.asyncio
    async def test_an_unknown_route_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await create_journal(SqlJournalRepository(clean_database))

        async with authenticated_lifespan_client() as client:
            payload = await _call(
                client,
                "delete_journal_route",
                {"journal_id": journal_id, "route_id": str(uuid4())},
            )

        assert payload["error"] == "Route not found"
        assert await _route_event_payloads(clean_database, "RouteDeleted") == []
