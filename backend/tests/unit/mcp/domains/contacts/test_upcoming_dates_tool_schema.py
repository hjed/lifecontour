"""The contract ``list_upcoming_important_dates`` publishes to an agent.

An MCP tool's whole interface is its name, its parameter schema and its prose:
there is no type checker on the other side and no client to read a convention
out of the code. So the schema is asserted rather than assumed, and so is what
the tool **refuses** to take — a parameter that exists is a parameter an agent
will eventually pass, and each of the absent ones would let it ask a question
this tool must not answer.

Mirrors ``tests/unit/mcp/domains/test_task_tools_schema.py``, which exists for
the sibling listing and for the same reason.
"""

from typing import Any

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.contacts.tools import register_contact_tools

pytestmark = pytest.mark.unit

TOOL = "list_upcoming_important_dates"


@pytest.fixture
def mcp_server() -> FastMCP[None]:
    server: FastMCP[None] = FastMCP(name="Test")
    register_contact_tools(server)
    return server


async def tool_schema(server: FastMCP[None]) -> dict[str, Any]:
    """The published input schema for the tool under test."""
    async with Client(server) as client:
        tools = await client.list_tools()

    for tool in tools:
        if tool.name == TOOL:
            return dict(tool.inputSchema)
    raise AssertionError(f"{TOOL} is not registered")


async def tool_description(server: FastMCP[None]) -> str:
    async with Client(server) as client:
        tools = await client.list_tools()

    for tool in tools:
        if tool.name == TOOL:
            description: str | None = tool.description
            assert description is not None
            return description
    raise AssertionError(f"{TOOL} is not registered")


class TestItIsRegistered:
    async def test_the_tool_exists_on_the_contacts_surface(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """Delivery rule 5: the capability lands on MCP in the same phase as the
        page, and the specification says an agent composes the dashboard from
        "the contacts tools for upcoming dates"."""
        async with Client(mcp_server) as client:
            names = [tool.name for tool in await client.list_tools()]

        assert TOOL in names


class TestTheWindowParameter:
    async def test_days_ahead_defaults_to_seven_in_the_schema(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """In the schema, not only in the sentence: a client reads the schema."""
        schema = await tool_schema(mcp_server)

        assert schema["properties"]["days_ahead"]["default"] == 7

    async def test_days_ahead_is_bounded_at_both_ends(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """Zero is today alone, and the upper bound is the domain's, so an agent
        cannot turn a dashboard window into a listing of every date on file."""
        days_ahead = (await tool_schema(mcp_server))["properties"]["days_ahead"]

        assert days_ahead["minimum"] == 0
        assert days_ahead["maximum"] == 90

    async def test_it_is_the_only_parameter(self, mcp_server: FastMCP[None]) -> None:
        schema = await tool_schema(mcp_server)

        assert set(schema["properties"]) == {"days_ahead"}

    async def test_nothing_is_required(self, mcp_server: FastMCP[None]) -> None:
        """Asking with no arguments at all is the ordinary call."""
        schema = await tool_schema(mcp_server)

        assert schema.get("required", []) == []


class TestWhatItRefusesToTake:
    """Each absent parameter would let an agent ask a question this must not answer."""

    @pytest.mark.parametrize("refused", ["now", "today", "date", "anchor"])
    async def test_the_anchor_cannot_be_moved(
        self, mcp_server: FastMCP[None], refused: str
    ) -> None:
        """The window is anchored on today in the user's own timezone. A tool
        that let an agent supply the day would let it ask about a different one
        and present the answer as "coming up"."""
        assert refused not in (await tool_schema(mcp_server))["properties"]

    @pytest.mark.parametrize("refused", ["user_id", "owner_id"])
    async def test_the_acting_user_cannot_be_named(
        self, mcp_server: FastMCP[None], refused: str
    ) -> None:
        """The session says who is asking; a parameter would be impersonation."""
        assert refused not in (await tool_schema(mcp_server))["properties"]

    @pytest.mark.parametrize("refused", ["page", "limit", "offset"])
    async def test_it_is_not_paginated(
        self, mcp_server: FastMCP[None], refused: str
    ) -> None:
        """The window is what bounds this answer. Paging controls would advertise
        a second page that does not exist and imply the first was truncated."""
        assert refused not in (await tool_schema(mcp_server))["properties"]

    @pytest.mark.parametrize("refused", ["date_type", "contact_id"])
    async def test_it_does_not_filter(
        self, mcp_server: FastMCP[None], refused: str
    ) -> None:
        """Every date type participates — precision alone decides whether a date
        recurs — so a type filter would be a second rule overlapping the first."""
        assert refused not in (await tool_schema(mcp_server))["properties"]


class TestWhatTheDescriptionMustSay:
    """The whole contract beyond one integer is prose, so the prose is asserted."""

    async def test_it_names_the_default_window(self, mcp_server: FastMCP[None]) -> None:
        assert "seven" in (await tool_description(mcp_server)).lower()

    async def test_it_says_the_window_is_anchored_in_the_users_timezone(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """An agent that computed "days away" from a timestamp would drift a day."""
        assert "timezone" in (await tool_description(mcp_server)).lower()

    async def test_it_warns_that_a_missing_year_means_no_derived_count(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """Otherwise an agent invents an age from a date recorded without a year."""
        description = (await tool_description(mcp_server)).lower()

        assert "years" in description
        assert "null" in description

    async def test_it_explains_the_leap_day_substitution(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """A 29 February date reported as the 28th looks like bad data unless the
        tool says it is a stand-in and which flag names it."""
        description = (await tool_description(mcp_server)).lower()

        assert "29 february" in description
        assert "observed_for_leap_day" in description

    async def test_it_says_an_empty_answer_is_an_ordinary_one(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """So an agent reports a quiet week rather than retrying or apologising."""
        assert "empty" in (await tool_description(mcp_server)).lower()
