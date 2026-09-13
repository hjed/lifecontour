"""Route refusals and large arguments through the unified MCP error handler."""

import json
from typing import Any

import pytest
from core_shared.models.journals import RouteValidationError

from app.mcp.shared import decorators
from app.mcp.shared.decorators import mcp_unified_error_handler


@pytest.mark.asyncio
async def test_route_validation_error_names_the_field() -> None:
    @mcp_unified_error_handler("create_journal_route", "journal")
    async def tool() -> str:
        raise RouteValidationError("gpx_data", "GPX data must be valid XML")

    payload = json.loads(await tool())

    assert payload["error"] == "Validation error"
    assert payload["field"] == "gpx_data"
    assert payload["message"] == (
        "Validation failed for gpx_data: GPX data must be valid XML"
    )


@pytest.mark.asyncio
async def test_long_string_arguments_are_not_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A multi-megabyte GPX argument must not be copied into the logs.

    Patched rather than captured: the app caches its structlog loggers, so a
    swapped processor chain silently captures nothing once anything has logged.
    """
    logged: list[dict[str, Any]] = []

    def record(operation: str, **kwargs: Any) -> None:
        logged.append(kwargs)

    monkeypatch.setattr(decorators.MCPLogger, "log_operation_start", record)
    gpx_data = "<gpx>" + "x" * 5000 + "</gpx>"

    @mcp_unified_error_handler("create_journal_route", "journal")
    async def tool(name: str, gpx_data: str) -> str:
        return "ok"

    assert await tool(name="Harbour Loop", gpx_data=gpx_data) == "ok"

    assert logged == [{"name": "Harbour Loop", "gpx_data": "<str: 5011 chars>"}]
