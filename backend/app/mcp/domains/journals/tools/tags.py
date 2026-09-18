"""MCP tools for journal tags (a separate namespace from contact tags)."""

from typing import Annotated
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalValidationError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.journal_tag_service import JournalTagService
from app.mcp.domains.journals.schemas import (
    JournalTagInfo,
    JournalTagListMCPResponse,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
)

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data
from app.mcp.shared.annotations import (
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_journal_tag_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_journal_tags", "tag")
async def list_journal_tags(
    limit: Annotated[
        int, Field(description="Maximum number of tags to return", ge=1, le=100)
    ] = 50,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all available journal tags for organising journal entries.

    Journal tags are a separate namespace from contact tags — use
    list_contact_tags for those. Tags are hierarchical: a tag with a
    parent_id is a child of that tag, and a null parent_id marks a root tag.

    Args:
        limit: Maximum number of tags to return (1-100, default: 50)

    Returns:
        JSON string containing journal tags ordered by name, each with its
        colour, description, and parent_id for reconstructing the hierarchy.
    """
    repos = create_journal_tool_repositories(db_connection)

    all_tags = await repos.tag_repo.get_all()
    tags = all_tags[:limit]

    tag_data = [
        JournalTagInfo(
            id=str(tag.id),
            name=tag.name,
            color=tag.color,
            description=tag.description,
            parent_id=str(tag.parent_id) if tag.parent_id else None,
            created_at=tag.created_at.isoformat() if tag.created_at else None,
        )
        for tag in tags
    ]

    response_data = JournalTagListMCPResponse(
        tags=tag_data,
        total_count=len(tag_data),
        summary=f"Found {len(tag_data)} journal tag(s). "
        "Journal tags categorise journal entries by theme, project, or activity.",
        suggestions=[
            "Use tags to group journals by theme (training, travel, reflection)",
            "Nest tags under a parent to build a hierarchy (activities/climbing)",
            "Assign tags when creating or updating a journal entry",
        ],
    )

    return MCPResponseBuilder.success_response(response_data)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_journal_tag", "tag")
async def update_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to update")],
    name: Annotated[
        str | None, Field(description="New tag name (must be unique)")
    ] = None,
    color: Annotated[
        str | None, Field(description="New hex colour code, e.g. #FF0000")
    ] = None,
    description: Annotated[
        str | None, Field(description="New description of what the tag is for")
    ] = None,
    parent_id: Annotated[
        str | None, Field(description="UUID of the new parent tag")
    ] = None,
    move_to_root: Annotated[
        bool,
        Field(description="Clear the tag's parent, making it a root tag"),
    ] = False,
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Update an existing journal tag's name, colour, description, or parent.

    Journal tags are a separate namespace from contact tags — use
    update_contact_tag for those, and list_journal_tags to find tag UUIDs.

    Only the arguments you supply are changed; omitted arguments are left as
    they are. To move a tag to the root of the hierarchy, pass
    move_to_root=true rather than a null parent_id, since an omitted parent_id
    means "leave the parent alone".

    Args:
        tag_id: UUID of the tag to update
        name: New name; must not collide with another tag (case-insensitive)
        color: New hex colour code (7 characters, e.g. #FF0000)
        description: New description of what the tag is for
        parent_id: UUID of the new parent tag
        move_to_root: Clear the parent instead of setting one

    Returns:
        JSON string containing the updated tag.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    parent_uuid = None
    if parent_id is not None:
        try:
            parent_uuid = UUID(parent_id)
        except ValueError as e:
            raise JournalValidationError(
                "parent_id", f"Invalid parent tag UUID: {parent_id}"
            ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    updated = await tag_service.update_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        name=name,
        color=color,
        description=description,
        parent_id=parent_uuid,
        set_parent_null=move_to_root,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    response_data = JournalTagInfo(
        id=str(updated.id),
        name=updated.name,
        color=updated.color,
        description=updated.description,
        parent_id=str(updated.parent_id) if updated.parent_id else None,
        created_at=updated.created_at.isoformat() if updated.created_at else None,
    )

    return MCPResponseBuilder.success_response(response_data)


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_journal_tag", "tag")
async def delete_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to delete")],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Delete a journal tag, removing it from every journal it is assigned to.

    Journal tags are a separate namespace from contact tags — use
    delete_contact_tag for those, and list_journal_tags to find tag UUIDs.

    This is not blocked when the tag is in use: journals keep their content and
    simply lose this tag. Any child tags of the deleted tag are re-parented to
    the root of the hierarchy rather than being deleted.

    Args:
        tag_id: UUID of the tag to delete

    Returns:
        JSON string confirming the deletion.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.delete_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class DeleteJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        DeleteJournalTagResponse(
            status="success",
            summary=f"Deleted journal tag {tag_id} and removed it from all journals",
        )
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("merge_journal_tag", "tag")
async def merge_journal_tag(
    source_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge away and delete")
    ],
    target_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge into (the survivor)")
    ],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Merge one journal tag into another, consolidating duplicates.

    Journal tags are a separate namespace from contact tags — use
    merge_contact_tags for those, and list_journal_tags to find tag UUIDs.

    Every journal tagged with the source tag ends up tagged with the target
    instead; a journal already carrying both keeps a single tag. Child tags of
    the source are adopted by the target rather than moved to the root. The
    source tag is then deleted.

    A tag cannot be merged into itself, nor into one of its own descendants —
    the surviving hierarchy would run through a tag that no longer exists.

    Args:
        source_tag_id: UUID of the tag to merge away and delete
        target_tag_id: UUID of the tag that survives the merge

    Returns:
        JSON string confirming the merge.
    """
    try:
        source_uuid = UUID(source_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "source_tag_id", f"Invalid tag UUID: {source_tag_id}"
        ) from e

    try:
        target_uuid = UUID(target_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "target_tag_id", f"Invalid tag UUID: {target_tag_id}"
        ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.merge_tag(
        source_id=source_uuid,
        target_id=target_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class MergeJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        MergeJournalTagResponse(
            status="success",
            summary=(
                f"Merged journal tag {source_tag_id} into {target_tag_id}; "
                "the source tag was deleted"
            ),
        )
    )


def register_journal_tag_tools(mcp: FastMCP[None]) -> None:
    """Register the tags MCP tools with the FastMCP server."""
    mcp.add_tool(list_journal_tags)
    mcp.add_tool(update_journal_tag)
    mcp.add_tool(delete_journal_tag)
    mcp.add_tool(merge_journal_tag)
