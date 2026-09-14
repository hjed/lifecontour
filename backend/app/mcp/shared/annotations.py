"""The behaviour hints every MCP tool declares about itself.

The MCP specification gives a tool four hints — ``readOnlyHint``,
``destructiveHint``, ``idempotentHint`` and ``openWorldHint`` — that tell a
client what calling it will do: whether to confirm with the user first,
whether a retry is safe, and whether the call reaches beyond this system.
Those are the wire names; the MCP SDK's ``ToolAnnotations`` spells the fields
in snake_case (``read_only_hint`` and so on) and serializes them under the
camelCase aliases.

Every one of them is optional in ``ToolAnnotations``, and unset means "assume
the worst". This module makes them impossible to forget, in two steps:

``mcp_tool_annotations`` takes all four as *required* keyword arguments, so a
missing hint is a type error rather than a silently absent annotation, and it
rejects combinations the specification rules out.

The presets below then name the shapes our tools actually have. A tool cites
one of them, which keeps the four values in this single table instead of
retyped at eighty-odd call sites — and makes "which tools can delete
something?" answerable by reading one file.

Registration goes through whichever pattern a domain uses::

    @tool(annotations=IDEMPOTENT_WRITE)        # module-level + mcp.add_tool(fn)
    async def update_task_text(...) -> str: ...

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)   # closure inside register_*_tools
    async def delete_contact_tag(...) -> str: ...

``tests/unit/mcp/test_tool_annotations.py`` enforces that every registered
tool arrives with all four hints set, whichever pattern it used.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations


def mcp_tool_annotations(
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> ToolAnnotations:
    """Build a complete set of tool hints.

    All four arguments are keyword-only and required, which is the point:
    ``ToolAnnotations`` accepts any subset, so building one directly lets a
    hint go missing without complaint. Here mypy catches it.

    Args:
        read_only: The tool changes nothing — it only reports.
        destructive: The tool may remove or overwrite data, rather than only
            adding to it. Meaningful only for a tool that writes.
        idempotent: Calling it twice with the same arguments leaves the same
            state as calling it once.
        open_world: The tool interacts with systems outside this one — a
            third-party API, or a model. False means its whole world is our
            own data.

    Returns:
        The annotations to hand to ``@tool`` or ``@mcp.tool``.

    Raises:
        ValueError: If the combination contradicts itself. A read-only tool
            cannot destroy anything, and reading the same thing twice cannot
            help but be idempotent, so those pairings are mistakes rather
            than unusual choices.
    """
    if read_only and destructive:
        raise ValueError(
            "a read-only tool cannot be destructive: it changes nothing to destroy"
        )
    if read_only and not idempotent:
        raise ValueError(
            "a read-only tool is always idempotent: it leaves no state to differ"
        )

    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


# Reads of the user's own data: journals, contacts, tasks, search.
READ_ONLY = mcp_tool_annotations(
    read_only=True,
    destructive=False,
    idempotent=True,
    open_world=False,
)

# Reads that answer from a third-party system — Immich's photo library, an
# integration's live connection status — rather than from our database.
#
# Generating an AI summary belongs here too. Such a tool does write: it calls a
# model and caches what came back. But the hints describe the world the *caller*
# reasons about, and from there the cache is invisible — asking for a summary
# reads a summary, and asking twice reads the same one. Annotating it as a write
# would make a client confirm before what is, to the user, a read.
READ_ONLY_EXTERNAL = mcp_tool_annotations(
    read_only=True,
    destructive=False,
    idempotent=True,
    open_world=True,
)

# Writes that only add, and that a second call would add to again: creating a
# journal, a task, a template — and toggles, whose second call undoes the
# first and so is emphatically not idempotent.
ADDITIVE_WRITE = mcp_tool_annotations(
    read_only=False,
    destructive=False,
    idempotent=False,
    open_world=False,
)

# Writes that settle on a value rather than accumulating: updates, and links
# whose second application changes nothing.
IDEMPOTENT_WRITE = mcp_tool_annotations(
    read_only=False,
    destructive=False,
    idempotent=True,
    open_world=False,
)

# Writes that take something away: deletes, merges (which consume their
# source), and unlinks. Repeating one is harmless — the data is already gone —
# which is why these are idempotent as well as destructive.
DESTRUCTIVE_WRITE = mcp_tool_annotations(
    read_only=False,
    destructive=True,
    idempotent=True,
    open_world=False,
)

# Writes whose effect lands in a third-party system and accumulates there:
# each call queues another sync, or creates another album.
EXTERNAL_ADDITIVE_WRITE = mcp_tool_annotations(
    read_only=False,
    destructive=False,
    idempotent=False,
    open_world=True,
)


__all__ = [
    "ADDITIVE_WRITE",
    "DESTRUCTIVE_WRITE",
    "EXTERNAL_ADDITIVE_WRITE",
    "IDEMPOTENT_WRITE",
    "READ_ONLY",
    "READ_ONLY_EXTERNAL",
    "mcp_tool_annotations",
]
