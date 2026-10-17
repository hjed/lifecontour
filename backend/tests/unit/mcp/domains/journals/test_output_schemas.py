"""The result shapes of the journal tools that used to return raw JSON.

Each is published as the tool's outputSchema, which is the only description
of the answer a client gets: fastmcp strips ``Returns:`` sections from tool
descriptions.
"""

from typing import Any

import pytest
from fastmcp import Client

from app.mcp.server import create_mcp_server

_SERIES_FIELDS = {
    "id",
    "name",
    "description",
    "calendar_id",
    "recurring_event_id",
    "auto_created",
    "created_at",
    "updated_at",
}
_MERGE_FIELDS = {"source_series_id", "destination_series_id", "days", "journals"}


@pytest.fixture
async def output_schemas() -> dict[str, dict[str, Any] | None]:
    async with Client(create_mcp_server()) as client:
        return {tool.name: tool.output_schema for tool in await client.list_tools()}


@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("create_series", _SERIES_FIELDS),
        ("update_series", _SERIES_FIELDS),
        ("get_series", _SERIES_FIELDS | {"member_journals"}),
        ("list_series", {"series"}),
        ("delete_series", {"deleted", "series_id"}),
        ("add_journal_to_series", {"added", "series_id", "journal_id"}),
        ("remove_journal_from_series", {"removed", "series_id", "journal_id"}),
        ("preview_series_merge", _MERGE_FIELDS),
        ("merge_series", _MERGE_FIELDS),
        ("list_review_items", {"meta", "data", "summary"}),
        ("dismiss_review_item", {"success", "message", "status"}),
        (
            "list_journal_types",
            {
                "journal_types",
                "contact_relationship_enums",
                "enums",
                "units",
                "usage_hint",
            },
        ),
        ("get_daily_summary", {"data"}),
    ],
)
async def test_the_tool_publishes_its_fields(
    output_schemas: dict[str, dict[str, Any] | None], name: str, fields: set[str]
) -> None:
    schema = output_schemas[name]

    assert schema is not None, f"{name} publishes no outputSchema"
    assert set(schema["properties"]) == fields


async def test_a_merge_day_says_what_happens_to_it(
    output_schemas: dict[str, dict[str, Any] | None],
) -> None:
    """The day's outcome is a closed set an agent branches on."""
    schema = output_schemas["preview_series_merge"]
    assert schema is not None

    day = schema["properties"]["days"]["items"]
    assert "enum" in day["properties"]["kind"]


async def test_a_missing_daily_summary_is_a_null_data_field(
    output_schemas: dict[str, dict[str, Any] | None],
) -> None:
    """One shape for both answers: the summary, or null when there is none."""
    schema = output_schemas["get_daily_summary"]
    assert schema is not None

    variants = schema["properties"]["data"]["anyOf"]
    assert {"type": "null"} in variants
