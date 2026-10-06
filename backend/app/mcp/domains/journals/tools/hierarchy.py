"""MCP tool returning journals as a parent/child hierarchy."""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.hierarchy_service import HierarchyNode, HierarchyService
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
)
from app.mcp.domains.journals.schemas import (
    EventDateRangeSchema,
    JournalHierarchyNode,
    JournalHierarchyResponse,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
    parse_optional_datetime_filter,
    parse_type_filters,
)
from app.mcp.shared.annotations import (
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_enrichment_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


async def _build_hierarchy_node(
    node: HierarchyNode, types_by_id: dict[int, list[str]]
) -> JournalHierarchyNode:
    """Build an AI-friendly hierarchy node from a HierarchyNode."""
    assert node.journal.id is not None, "Hierarchy node journal must have an ID"
    types = types_by_id.get(node.journal.id, [])
    children = [
        await _build_hierarchy_node(child_node, types_by_id)
        for child_node in node.children
    ]

    return JournalHierarchyNode(
        id=node.journal.id or 0,
        title=node.journal.title,
        content_excerpt=node.journal.content[:200] + "..."
        if len(node.journal.content) > 200
        else node.journal.content,
        event_date_range=EventDateRangeSchema(
            start=node.journal.event_date_range.start,
            end=node.journal.event_date_range.end,
        ),
        types=types,
        tags=[],
        highlighted={},
        summary=f"Hierarchical Journal: {node.journal.title}",
        depth=node.depth,
        children_count=node.children_count,
        children=children,
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_hierarchy", "journal")
async def get_journal_hierarchy(
    start_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Start date (ISO format) to filter journals",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: End date (ISO format) to filter journals",
        ),
    ] = None,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated list of journal types to filter by",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=100,
            description="Maximum number of journals to retrieve before building hierarchy (default: 100)",
        ),
    ] = 100,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """
    Get a hierarchical view of journals.

    Retrieves journals and their descendants matching the given filters,
    returning them in a nested tree structure. Useful for exploring
    trips, projects, or multi-day events.

    Args:
        start_date: Optional start date
        end_date: Optional end date
        types: Optional comma-separated list of journal types
        limit: Maximum number of journals to retrieve

    Returns:
        JSON string containing the journal hierarchy tree and summary.
    """
    import time

    start_time = time.time()
    user_id = await get_current_user_id()
    repos = create_journal_tool_repositories(db_connection)

    type_filters = parse_type_filters(types)
    journal_type = type_filters[0] if len(type_filters) == 1 else None

    start = parse_optional_datetime_filter(start_date, "start_date")
    end = parse_optional_datetime_filter(end_date, "end_date", is_end=True)

    start_str = start.isoformat() if start else None
    end_str = end.isoformat() if end else None

    journals = await repos.journal_repo.get_all(
        user_id=user_id,
        limit=limit,
        offset=0,
        journal_type=journal_type,
        start_date=start_str,
        end_date=end_str,
    )

    types_by_id = await enrichment_service.types_for(
        [j.id for j in journals if j.id is not None]
    )
    if len(type_filters) > 1:
        journals = [
            j
            for j in journals
            if j.id is not None
            and any(t in type_filters for t in types_by_id.get(j.id, []))
        ]

    returned_ids_list = [j.id for j in journals if j.id is not None]
    children_count_by_parent_id = await repos.journal_repo.count_children_for_parents(
        user_id=user_id, parent_ids=returned_ids_list
    )

    depth_map = await HierarchyService.compute_depth_map(
        returned_ids_list, repos.journal_repo
    )

    hierarchy_nodes = HierarchyService.build_tree_nodes(
        journals, children_count_by_parent_id, depth_map
    )

    root_nodes = []
    for h_node in hierarchy_nodes:
        root_nodes.append(await _build_hierarchy_node(h_node, types_by_id))

    processing_time_ms = int((time.time() - start_time) * 1000)
    summary = (
        f"Found {len(journals)} journal(s), representing {len(root_nodes)} "
        f"root-level item(s) in the hierarchy. (Processing time: {processing_time_ms}ms)"
    )

    response = JournalHierarchyResponse(
        nodes=root_nodes,
        total_nodes=len(journals),
        processing_time_ms=processing_time_ms,
        summary=summary,
    )

    return MCPResponseBuilder.success_response(response)


def register_journal_hierarchy_tools(mcp: FastMCP[None]) -> None:
    """Register the hierarchy MCP tools with the FastMCP server."""
    mcp.add_tool(get_journal_hierarchy)
