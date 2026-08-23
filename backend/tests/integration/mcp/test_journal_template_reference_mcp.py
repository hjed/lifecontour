"""Integration tests for the consolidated ``template_id`` over MCP (ITER16-001 Phase 2).

The consolidated ``abseiling_data.template_id`` is written/read at the abseiling
level via the ``ABSEILING_TRIP`` type-data block for every abseiling-derived journal.
These tests exercise the MCP parity surface:

* ``create_journal_entry`` / ``update_journal_entry`` accept and preserve it, and
* ``get_journal_template`` retrieves the referenced template (incl. its standard
  pitches) even after the journal's own pitches are edited.
"""

from typing import Any

import pytest

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)

# Each abseiling-derived journal type paired with a same-typed template.
_DERIVED_TYPES = [
    ("CANYONING", "canyoning"),
    ("CLIMBING", "climbing"),
    ("CAVING", "caving"),
    ("ABSEILING_TRIP", "abseiling"),
]


async def _call_tool(
    client, session_id: str, name: str, arguments: dict[str, Any], req_id: int = 1
) -> dict[str, Any]:
    response = await client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=mcp_headers(session_id),
    )
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _create_template(client, session_id: str, template_type: str) -> str:
    payload = await _call_tool(
        client,
        session_id,
        "create_template",
        {
            "name": f"{template_type.title()} Template",
            "template_type": template_type,
            "region": "Blue Mountains",
            "pitches": [
                {"pitch_number": 1, "height": 30, "anchor_type": "double bolt"}
            ],
        },
    )
    assert "error" not in payload, payload
    return str(payload["id"])


async def _create_journal_with_template(
    client,
    session_id: str,
    journal_type: str,
    template_id: str,
) -> int:
    payload = await _call_tool(
        client,
        session_id,
        "create_journal_entry",
        {
            "request": {
                "title": f"{journal_type} with template",
                "content": "Created from a template.",
                "event_date_range": {
                    "start": "2025-04-09T00:00:00Z",
                    "end": "2025-04-09T05:00:00Z",
                },
                "types": [journal_type],
                "type_data": {
                    "ABSEILING_TRIP": {
                        "template_id": template_id,
                        "pitches": [{"pitch_number": 1, "height": 20}],
                    }
                },
            }
        },
    )
    assert "error" not in payload, payload
    return int(payload["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_type,template_type", _DERIVED_TYPES)
async def test_mcp_create_persists_consolidated_template_id(
    authenticated_lifespan_client, journal_type: str, template_type: str
) -> None:
    """create_journal_entry persists template_id for every abseiling-derived type."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_template(client, session_id, template_type)
        journal_id = await _create_journal_with_template(
            client, session_id, journal_type, template_id
        )

        result = await _call_tool(
            client, session_id, "get_journal_template", {"journal_id": journal_id}
        )
        assert "error" not in result, result
        assert result["has_template"] is True
        assert result["template"]["id"] == template_id


@pytest.mark.asyncio
async def test_mcp_pitch_only_update_preserves_template_id(
    authenticated_lifespan_client,
) -> None:
    """A pitch-only update_journal_entry must not clear the template reference."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_template(client, session_id, "canyoning")
        journal_id = await _create_journal_with_template(
            client, session_id, "CANYONING", template_id
        )

        update = await _call_tool(
            client,
            session_id,
            "update_journal_entry",
            {
                "journal_id": journal_id,
                "request": {
                    "type_data": {
                        "ABSEILING_TRIP": {
                            "pitches": [
                                {"pitch_number": 1, "height": 45},
                                {"pitch_number": 2, "height": 12},
                            ]
                        }
                    }
                },
            },
            req_id=2,
        )
        assert "error" not in update, update

        result = await _call_tool(
            client, session_id, "get_journal_template", {"journal_id": journal_id}
        )
        assert result["has_template"] is True
        assert result["template"]["id"] == template_id


@pytest.mark.asyncio
async def test_mcp_get_journal_template_returns_standard_pitches(
    authenticated_lifespan_client,
) -> None:
    """Retrieval returns the template's standard pitches despite edited journal pitches."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_template(client, session_id, "canyoning")
        journal_id = await _create_journal_with_template(
            client, session_id, "CANYONING", template_id
        )

        # Edit the journal's own pitches away from the template's single 30m pitch.
        await _call_tool(
            client,
            session_id,
            "update_journal_entry",
            {
                "journal_id": journal_id,
                "request": {
                    "type_data": {
                        "ABSEILING_TRIP": {
                            "pitches": [
                                {"pitch_number": 1, "height": 5},
                                {"pitch_number": 2, "height": 6},
                                {"pitch_number": 3, "height": 7},
                            ]
                        }
                    }
                },
            },
            req_id=2,
        )

        result = await _call_tool(
            client, session_id, "get_journal_template", {"journal_id": journal_id}
        )
        assert result["has_template"] is True
        # The template keeps its single standard 30m pitch, not the journal's 3.
        assert len(result["template"]["pitches"]) == 1
        assert result["template"]["pitches"][0]["height"] == 30


@pytest.mark.asyncio
async def test_mcp_template_pitch_notes_round_trip(
    authenticated_lifespan_client,
) -> None:
    """Template pitch notes survive create_template, get_template, update_template."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)

        created = await _call_tool(
            client,
            session_id,
            "create_template",
            {
                "name": "Notes Canyon",
                "template_type": "canyoning",
                "pitches": [
                    {
                        "pitch_number": 1,
                        "height": 30,
                        "notes": "Awkward start over the chockstone",
                        "pitch_type": "jump",
                    }
                ],
            },
        )
        assert "error" not in created, created
        template_id = str(created["id"])
        assert created["pitches"][0]["notes"] == "Awkward start over the chockstone"
        assert created["pitches"][0]["pitch_type"] == "jump"

        fetched = await _call_tool(
            client, session_id, "get_template", {"template_id": template_id}, req_id=2
        )
        assert fetched["pitches"][0]["notes"] == "Awkward start over the chockstone"
        assert fetched["pitches"][0]["pitch_type"] == "jump"

        updated = await _call_tool(
            client,
            session_id,
            "update_template",
            {
                "template_id": template_id,
                "pitches": [
                    {
                        "pitch_number": 1,
                        "height": 30,
                        "notes": "Rebolted in 2026",
                        "pitch_type": "abseil",
                    }
                ],
            },
            req_id=3,
        )
        assert "error" not in updated, updated
        assert updated["pitches"][0]["notes"] == "Rebolted in 2026"
        assert updated["pitches"][0]["pitch_type"] == "abseil"


@pytest.mark.asyncio
async def test_mcp_get_journal_template_when_none_set(
    authenticated_lifespan_client,
) -> None:
    """A journal with no template reference returns a clean has_template=False."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        payload = await _call_tool(
            client,
            session_id,
            "create_journal_entry",
            {
                "request": {
                    "title": "Plain abseiling trip",
                    "content": "No template.",
                    "event_date_range": {
                        "start": "2025-04-09T00:00:00Z",
                        "end": "2025-04-09T05:00:00Z",
                    },
                    "types": ["ABSEILING_TRIP"],
                    "type_data": {
                        "ABSEILING_TRIP": {
                            "pitches": [{"pitch_number": 1, "height": 20}]
                        }
                    },
                }
            },
        )
        journal_id = payload["id"]

        result = await _call_tool(
            client, session_id, "get_journal_template", {"journal_id": journal_id}
        )
        assert "error" not in result, result
        assert result["has_template"] is False
        assert result["template"] is None


# --- Applying a template on create (top-level ``template_id``) -----------------
#
# Picking a template in the web create form seeds the journal with the
# template's standard pitches, the abseil counts derived from them, and the
# template's own type fields. The MCP tool offers the same thing as a top-level
# ``template_id``, so an agent does not have to copy any of it by hand.


async def _create_rich_template(
    client, session_id: str, template_type: str, **fields
) -> str:
    """Create a template with two pitches plus any type-specific fields."""
    payload = await _call_tool(
        client,
        session_id,
        "create_template",
        {
            "name": f"Applied {template_type.title()} Template",
            "template_type": template_type,
            "region": "Blue Mountains",
            "pitches": [
                {"pitch_number": 1, "height": 30, "anchor_type": "double bolt"},
                {"pitch_number": 2, "height": 15, "pitch_type": "jump"},
            ],
            **fields,
        },
    )
    assert "error" not in payload, payload
    return str(payload["id"])


async def _create_from_template(
    client,
    session_id: str,
    journal_type: str,
    template_id: str,
    *,
    title: str = "Applied from template",
    type_data: dict[str, Any] | None = None,
    req_id: int = 2,
) -> dict[str, Any]:
    """Call create_journal_entry with a top-level template_id."""
    request: dict[str, Any] = {
        "title": title,
        "content": "Created from a template.",
        "event_date_range": {
            "start": "2025-04-09T00:00:00Z",
            "end": "2025-04-09T05:00:00Z",
        },
        "types": [journal_type],
        "template_id": template_id,
    }
    if type_data is not None:
        request["type_data"] = type_data
    return await _call_tool(
        client, session_id, "create_journal_entry", {"request": request}, req_id=req_id
    )


async def _read_type_data(client, journal_id: int) -> dict[str, Any]:
    """Read a journal's persisted type data over REST (it carries the pitches)."""
    response = await client.get(f"/api/journals/{journal_id}")
    assert response.status_code == 200, response.text
    return dict(response.json()["data"]["attributes"]["type_data"])


@pytest.mark.asyncio
@pytest.mark.parametrize("journal_type,template_type", _DERIVED_TYPES)
async def test_mcp_create_applies_template_pitches(
    authenticated_lifespan_client, journal_type: str, template_type: str
) -> None:
    """A top-level template_id seeds pitches and counts for every derived type."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_rich_template(client, session_id, template_type)

        created = await _create_from_template(
            client, session_id, journal_type, template_id
        )
        assert "error" not in created, created

        type_data = await _read_type_data(client, int(created["id"]))
        abseiling = type_data["abseiling_trip"]
        assert abseiling["template_id"] == template_id
        assert [p["height"] for p in abseiling["pitches"]] == [30, 15]
        assert abseiling["pitches"][0]["anchor_type"] == "double bolt"
        # The jump is measured but is not an abseil.
        assert abseiling["number_of_abseils"] == 1
        assert abseiling["total_length"] == 45

        reference = await _call_tool(
            client,
            session_id,
            "get_journal_template",
            {"journal_id": created["id"]},
            req_id=3,
        )
        assert reference["has_template"] is True
        assert reference["template"]["id"] == template_id


@pytest.mark.asyncio
async def test_mcp_create_applies_canyoning_fields(
    authenticated_lifespan_client,
) -> None:
    """A canyoning template also seeds the canyoning block."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_rich_template(
            client,
            session_id,
            "canyoning",
            french_grade="v4a3IV",
            canyon_type="vertical",
            water_gauge_name="Kanangra Creek",
        )

        created = await _create_from_template(
            client, session_id, "CANYONING", template_id
        )
        assert "error" not in created, created

        canyoning = (await _read_type_data(client, int(created["id"])))["canyoning"]
        assert canyoning["french_grade"] == "v4a3IV"
        assert canyoning["water_guage_name"] == "Kanangra Creek"
        assert canyoning["is_vertical"] is True


@pytest.mark.asyncio
async def test_mcp_create_applies_climbing_fields(
    authenticated_lifespan_client,
) -> None:
    """A climbing template also seeds the climbing block."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_rich_template(
            client, session_id, "climbing", climbing_type="sport", grade=21, length=30
        )

        created = await _create_from_template(
            client, session_id, "CLIMBING", template_id
        )
        assert "error" not in created, created

        climbing = (await _read_type_data(client, int(created["id"])))["climbing"]
        assert climbing["climbing_type"] == "sport"
        assert climbing["grade"] == 21
        assert climbing["length"] == 30


@pytest.mark.asyncio
async def test_mcp_create_lets_supplied_type_data_win(
    authenticated_lifespan_client,
) -> None:
    """Explicit type_data beats the template, and counts follow the caller's pitches."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_rich_template(
            client, session_id, "canyoning", french_grade="v4a3IV"
        )

        created = await _create_from_template(
            client,
            session_id,
            "CANYONING",
            template_id,
            type_data={
                "ABSEILING_TRIP": {"pitches": [{"pitch_number": 1, "height": 8}]},
                "CANYONING": {"french_grade": "v2a1II"},
            },
        )
        assert "error" not in created, created

        type_data = await _read_type_data(client, int(created["id"]))
        abseiling = type_data["abseiling_trip"]
        assert [p["height"] for p in abseiling["pitches"]] == [8]
        # The counts follow the pitches that were actually stored.
        assert abseiling["number_of_abseils"] == 1
        assert abseiling["total_length"] == 8
        # The reference is still recorded.
        assert abseiling["template_id"] == template_id
        assert type_data["canyoning"]["french_grade"] == "v2a1II"


@pytest.mark.asyncio
async def test_mcp_create_rejects_an_unknown_template(
    authenticated_lifespan_client,
) -> None:
    """An unknown template id fails validation and writes no journal."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)

        created = await _create_from_template(
            client,
            session_id,
            "CANYONING",
            "00000000-0000-4000-8000-000000000000",
            title="Should not exist",
        )
        assert "error" in created, created
        assert "template_id" in created["message"]

        response = await client.get("/api/journals")
        assert response.status_code == 200, response.text
        titles = [j["attributes"]["title"] for j in response.json()["data"]]
        assert "Should not exist" not in titles


@pytest.mark.asyncio
async def test_mcp_create_rejects_a_malformed_template_id(
    authenticated_lifespan_client,
) -> None:
    """A template id that is not a UUID is a validation error, not a 500."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)

        created = await _create_from_template(
            client, session_id, "CANYONING", "not-a-uuid"
        )
        assert "error" in created, created
        assert "template_id" in created["message"]


@pytest.mark.asyncio
async def test_mcp_create_rejects_an_empty_template_id(
    authenticated_lifespan_client,
) -> None:
    """An empty template_id is malformed, not "no template"."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)

        created = await _create_from_template(client, session_id, "CANYONING", "")
        assert "error" in created, created
        assert "template_id" in created["message"]


@pytest.mark.asyncio
async def test_mcp_create_rejects_a_template_on_a_non_abseiling_journal(
    authenticated_lifespan_client,
) -> None:
    """A template cannot silently turn a note into an abseiling trip."""
    async with authenticated_lifespan_client() as client:
        session_id = await initialize_mcp_session(client)
        template_id = await _create_rich_template(client, session_id, "canyoning")

        created = await _create_from_template(client, session_id, "NOTE", template_id)
        assert "error" in created, created
        assert "template_id" in created["message"]
