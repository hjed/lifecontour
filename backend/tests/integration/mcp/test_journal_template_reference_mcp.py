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
