"""Every MCP tool must tell a client how it behaves.

The MCP specification lets a tool advertise four behaviour hints —
``readOnlyHint``, ``destructiveHint``, ``idempotentHint`` and
``openWorldHint`` — which is how a client decides whether a call needs
confirmation, can be retried, or is safe to make on its own. All four
default to *unset*, so a tool that says nothing is a tool a client has to
assume the worst about.

This module is the enforcement point for that. It assembles the real
server through ``create_mcp_server`` and inspects the tools as an MCP
client sees them, so a new tool is covered whichever way it was
registered: the module-level ``@tool``/``add_tool`` pattern used by
journals, series and tasks, or the ``@mcp.tool`` closure pattern used by
contacts and integrations. A tool added without annotations fails here.
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from mcp.types import Tool as MCPTool

from app.mcp.server import create_mcp_server
from app.mcp.shared.read_only_tools import READ_ONLY_TOOL_NAMES

#: The four hints every tool has to answer. Named here rather than
#: reflected off ``ToolAnnotations`` because that model also carries
#: ``title`` and allows extras — this is the required set, not the
#: available one. These are the SDK's Python field names; the camelCase
#: spellings are only the wire aliases, and reading them as attributes
#: would find nothing.
REQUIRED_HINTS = (
    "read_only_hint",
    "destructive_hint",
    "idempotent_hint",
    "open_world_hint",
)

#: Tools that may remove or overwrite data a user would miss.
#:
#: Spelled out rather than derived, because ``destructiveHint`` is the
#: hint with real consequences: it is what a client uses to decide
#: whether to ask before calling. A missing annotation is caught by
#: ``test_every_tool_declares_all_four_hints`` below; this test catches
#: the worse case of a *wrong* one, in either direction — a destructive
#: tool that claims to be additive, or an additive tool needlessly
#: flagged as destructive.
DESTRUCTIVE_TOOLS = frozenset(
    {
        # Journals
        "delete_journal",
        "delete_calendar",
        "merge_journals",
        "delete_journal_tag",
        "merge_journal_tag",
        # Journal series
        "delete_series",
        "remove_journal_from_series",
        # Tasks
        "delete_task",
        "unlink_task_from_contact",
        "detach_intermediate_journal_from_task",
        # Contacts
        "merge_contacts",
        "remove_contact_relationship",
        "delete_contact_tag",
        "merge_contact_tags",
    }
)


@pytest.fixture
async def registered_tools() -> dict[str, MCPTool]:
    """Every tool on the real server, as an MCP client receives it.

    Going through ``Client`` rather than the server's internals is
    deliberate: the annotations only matter if they survive into the
    wire format, so that is what gets asserted.
    """
    server = create_mcp_server()

    async with Client(server) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def test_server_registers_tools(registered_tools: dict[str, MCPTool]) -> None:
    """A guard on the guards: an empty listing would pass every test below."""
    assert len(registered_tools) > 50, (
        "the whole tool surface should be registered; "
        f"only found {sorted(registered_tools)}"
    )


def test_every_tool_declares_all_four_hints(
    registered_tools: dict[str, MCPTool],
) -> None:
    """No tool may leave a behaviour hint unset.

    This is the check that catches a newly added tool: annotations are
    optional to FastMCP, so nothing else would notice.
    """
    missing: dict[str, list[str]] = {}

    for name, tool in sorted(registered_tools.items()):
        annotations = tool.annotations
        if annotations is None:
            missing[name] = list(REQUIRED_HINTS)
            continue
        unset = [
            hint for hint in REQUIRED_HINTS if getattr(annotations, hint, None) is None
        ]
        if unset:
            missing[name] = unset

    assert not missing, (
        "every MCP tool must declare all four behaviour hints — annotate these "
        "with a preset from app.mcp.shared.annotations: "
        + "; ".join(f"{name} ({', '.join(hints)})" for name, hints in missing.items())
    )


def test_read_only_tools_are_neither_destructive_nor_repeat_sensitive(
    registered_tools: dict[str, MCPTool],
) -> None:
    """A tool that changes nothing cannot destroy anything or drift on retry."""
    contradictions: list[str] = []

    for name, tool in sorted(registered_tools.items()):
        annotations = tool.annotations
        assert annotations is not None, f"{name} has no annotations"
        if not annotations.read_only_hint:
            continue
        if annotations.destructive_hint:
            contradictions.append(f"{name} is read-only but flagged destructive")
        if not annotations.idempotent_hint:
            contradictions.append(f"{name} is read-only but flagged non-idempotent")

    assert not contradictions, "; ".join(contradictions)


def test_destructive_tools_are_exactly_the_expected_set(
    registered_tools: dict[str, MCPTool],
) -> None:
    """The tools that remove data are the ones we say remove data."""
    flagged = {
        name
        for name, tool in registered_tools.items()
        if tool.annotations is not None and tool.annotations.destructive_hint
    }

    unexpected = flagged - DESTRUCTIVE_TOOLS
    unflagged = DESTRUCTIVE_TOOLS & registered_tools.keys() - flagged
    stale = DESTRUCTIVE_TOOLS - registered_tools.keys()

    assert not unexpected, (
        "these tools claim to be destructive but are not in DESTRUCTIVE_TOOLS — "
        f"correct the annotation or add them to the list: {sorted(unexpected)}"
    )
    assert not unflagged, (
        "these tools remove data but are not annotated destructive: "
        f"{sorted(unflagged)}"
    )
    assert not stale, (
        f"DESTRUCTIVE_TOOLS names tools that no longer exist: {sorted(stale)}"
    )


def test_ai_summary_generation_reads_from_the_callers_view(
    registered_tools: dict[str, MCPTool],
) -> None:
    """Generating a summary is a read to whoever asked for it.

    ``get_daily_summary`` does write — it calls a model and caches the
    result. But a hint describes the world the *caller* reasons about, and
    from there the cache does not exist: asking for a summary gets a
    summary, and asking again gets the same one. Annotating it as a write
    would make a client confirm before what the user experiences as a
    read. It stays open-world, because a model is still involved.
    """
    annotations = registered_tools["get_daily_summary"].annotations
    assert annotations is not None

    assert annotations.read_only_hint is True
    assert annotations.open_world_hint is True


def test_curated_read_only_toolset_is_genuinely_read_only(
    registered_tools: dict[str, MCPTool],
) -> None:
    """The toolset handed to Gemini must agree with the tools' own hints.

    ``READ_ONLY_TOOL_NAMES`` is a hand-maintained list, and the AI summary
    generators trust it to expose only safe tools. Tying it to
    ``readOnlyHint`` means the two cannot drift apart silently — if a tool
    on that list ever gains a write, annotating it honestly breaks this
    test rather than quietly handing a write tool to the model.
    """
    not_read_only = [
        name
        for name in READ_ONLY_TOOL_NAMES
        if (tool := registered_tools.get(name)) is not None
        and not (tool.annotations is not None and tool.annotations.read_only_hint)
    ]

    assert not not_read_only, (
        "READ_ONLY_TOOL_NAMES exposes tools that do not declare readOnlyHint: "
        f"{not_read_only}"
    )

    unknown = [name for name in READ_ONLY_TOOL_NAMES if name not in registered_tools]
    assert not unknown, f"READ_ONLY_TOOL_NAMES names unregistered tools: {unknown}"
