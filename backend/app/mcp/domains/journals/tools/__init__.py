"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
Tools are moving into one module per area; ``register_journal_tools``
registers every one of them.
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    ActivityTemplate,
    CanyonType,
    ClimbingType,
    GearItem,
    JournalValidationError,
    TemplatePitch,
    TemplateType,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.activity_template_service import (
    ActivityTemplateService,
)
from app.core.journal.services.gear_item_service import GearItemService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.mcp.domains.journals.converters import (
    ActivityTemplateMCPConverter,
    GearItemMCPConverter,
)
from app.mcp.domains.journals.schemas import (
    JournalTagInfo,
    JournalTagListMCPResponse,
    JournalTemplateMCPResponse,
    TemplatePitchInput,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
)
from app.mcp.domains.journals.tools.activities import register_activity_tools

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data
from app.mcp.domains.journals.tools.calendars import register_calendar_tools
from app.mcp.domains.journals.tools.contacts import register_journal_contact_tools
from app.mcp.domains.journals.tools.daily_summary import register_daily_summary_tools
from app.mcp.domains.journals.tools.hierarchy import register_journal_hierarchy_tools
from app.mcp.domains.journals.tools.history import register_journal_history_tools
from app.mcp.domains.journals.tools.journal_entries import register_journal_entry_tools
from app.mcp.domains.journals.tools.journals import register_journal_read_tools
from app.mcp.domains.journals.tools.merge import register_journal_merge_tools
from app.mcp.domains.journals.tools.outdoor import register_outdoor_tools
from app.mcp.domains.journals.tools.review_items import register_review_item_tools
from app.mcp.domains.journals.tools.routes import register_journal_route_tools
from app.mcp.domains.journals.tools.search import register_journal_search_tools
from app.mcp.domains.journals.tools.series import register_journal_series_tools
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_template_service,
    get_async_connection,
    get_current_user_id,
    get_gear_item_service,
    get_journal_tag_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_template", "journal")
async def create_template(
    name: Annotated[str, Field(description="Template name")],
    template_type: Annotated[TemplateType, Field(description="Type of template")],
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Create a new activity template.
    """
    import uuid

    template_id = str(uuid.uuid4())
    pitch_entities: list[TemplatePitch] = []
    if pitches:
        pitch_entities.extend(
            TemplatePitch(template_id=template_id, **p.model_dump(mode="json"))
            for p in pitches
        )

    template = ActivityTemplate(
        id=template_id,
        user_id=user_id,
        name=name,
        template_type=template_type,
        region=region,
        description=description,
        french_grade=french_grade,
        canyon_type=canyon_type,
        water_gauge_name=water_gauge_name,
        is_vertical=is_vertical,
        is_horizontal=is_horizontal,
        climbing_type=climbing_type,
        grade=grade,
        length=length,
        pitches=pitch_entities,
    )

    saved_template = await activity_template_service.create(
        template, transaction=db_connection
    )

    response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_template", "journal")
async def get_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific activity template by ID.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        response = ActivityTemplateMCPConverter.to_mcp_response(template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_template", "journal")
async def get_journal_template(
    journal_id: Annotated[int, Field(description="Journal id")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Retrieve the activity template an abseiling-derived journal was created from.

    Returns the referenced template (including its own standard pitches) for any
    abseiling-derived journal (ABSEILING_TRIP / CANYONING / CLIMBING / CAVING),
    reading the consolidated ``abseiling_data.template_id``. The template's
    standard pitches are returned even when the journal's own pitches have been
    edited. ``has_template`` is false when the journal has no template reference
    (or is not abseiling-derived).
    """
    repos = create_journal_tool_repositories(db_connection)

    journal = await repos.journal_repo.find_by_id(journal_id)
    if not journal or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    abseiling_data = await repos.abseiling_data_repo.find_by_journal_id(journal_id)
    template = None
    if abseiling_data is not None and abseiling_data.template_id is not None:
        candidate = await repos.activity_template_repo.find_by_id(
            str(abseiling_data.template_id)
        )
        if candidate is not None and candidate.user_id == user_id:
            template = candidate

    if template is None:
        return MCPResponseBuilder.success_response(
            JournalTemplateMCPResponse(
                journal_id=journal_id,
                has_template=False,
                template=None,
                summary=f"Journal {journal_id} has no template reference.",
            )
        )

    return MCPResponseBuilder.success_response(
        JournalTemplateMCPResponse(
            journal_id=journal_id,
            has_template=True,
            template=ActivityTemplateMCPConverter.to_mcp_response(template),
            summary=f"Journal {journal_id} based on template: {template.name}.",
        )
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("search_templates", "journal")
async def search_templates(
    template_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional type of template (e.g. canyoning, climbing) to filter by",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Search activity templates for the user.
    """
    repos = create_journal_tool_repositories(db_connection)

    templates = await repos.activity_template_repo.find_by_user(user_id)

    if template_type:
        templates = [t for t in templates if t.template_type == template_type]

    response = ActivityTemplateMCPConverter.to_mcp_list_response(templates)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_template", "journal")
async def update_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    name: Annotated[
        str | None, Field(default=None, description="Template name")
    ] = None,
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Update an existing activity template.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        if name is not None:
            template.name = name
        if region is not None:
            template.region = region
        if description is not None:
            template.description = description
        if french_grade is not None:
            template.french_grade = french_grade
        if canyon_type is not None:
            template.canyon_type = canyon_type
        if water_gauge_name is not None:
            template.water_gauge_name = water_gauge_name
        if is_vertical is not None:
            template.is_vertical = is_vertical
        if is_horizontal is not None:
            template.is_horizontal = is_horizontal
        if climbing_type is not None:
            template.climbing_type = climbing_type
        if grade is not None:
            template.grade = grade
        if length is not None:
            template.length = length

        if pitches is not None:
            pitch_entities: list[TemplatePitch] = []
            pitch_entities.extend(
                TemplatePitch(template_id=str(template.id), **p.model_dump(mode="json"))
                for p in pitches
            )
            template.pitches = pitch_entities

        try:
            template.__post_init__()
        except Exception as e:  # noqa: BLE001
            return MCPResponseBuilder.validation_error_response("template", str(e))

        saved_template = await activity_template_service.update(
            template, transaction=db_connection
        )

        response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_gear_item", "journal")
async def create_gear_item(
    name: Annotated[str, Field(description="Gear item name")],
    model: Annotated[
        str | None, Field(default=None, description="Model name/number")
    ] = None,
    serial_number: Annotated[
        str | None, Field(default=None, description="Serial number")
    ] = None,
    purchase_date: Annotated[
        str | None, Field(default=None, description="Purchase date (YYYY-MM-DD)")
    ] = None,
    manufacturer: Annotated[
        str | None, Field(default=None, description="Manufacturer name")
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Create a new gear item for tracking equipment (ropes, harnesses, helmets, etc.).
    """
    parsed_purchase_date = None
    if purchase_date:
        try:
            parsed_purchase_date = date.fromisoformat(purchase_date)
        except ValueError:
            return MCPResponseBuilder.validation_error_response(
                "purchase_date", "Invalid date format, use YYYY-MM-DD"
            )

    item = GearItem(
        user_id=user_id,
        name=name,
        model=model,
        serial_number=serial_number,
        purchase_date=parsed_purchase_date,
        manufacturer=manufacturer,
    )

    saved_item = await gear_item_service.create(item, transaction=db_connection)

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_gear_items", "journal")
async def list_gear_items(
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all gear items for the current user.
    """
    repos = create_journal_tool_repositories(db_connection)

    items = await repos.gear_item_repo.find_by_user(user_id)

    response = GearItemMCPConverter.to_mcp_list_response(items)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_gear_item", "journal")
async def get_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific gear item by ID.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
        item = await repos.gear_item_repo.find_by_id(gear_item_id)
        if not item or item.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response(
                "Gear item", gear_item_id
            )

        response = GearItemMCPConverter.to_mcp_response(item)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_gear_item", "journal")
async def update_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    name: Annotated[str | None, Field(default=None, description="Updated name")] = None,
    model: Annotated[
        str | None,
        Field(default=None, description="Updated model (pass empty string to clear)"),
    ] = None,
    serial_number: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated serial number (pass empty string to clear)",
        ),
    ] = None,
    purchase_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated purchase date YYYY-MM-DD (pass empty string to clear)",
        ),
    ] = None,
    manufacturer: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated manufacturer (pass empty string to clear)",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Update an existing gear item.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )

    item = await repos.gear_item_repo.find_by_id(gear_item_id)
    if not item or item.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Gear item", gear_item_id)

    if name is not None:
        item.name = name
    if model is not None:
        item.model = None if model == "" else model
    if serial_number is not None:
        item.serial_number = None if serial_number == "" else serial_number
    if purchase_date is not None:
        if purchase_date == "":
            item.purchase_date = None
        else:
            try:
                item.purchase_date = date.fromisoformat(purchase_date)
            except ValueError:
                return MCPResponseBuilder.validation_error_response(
                    "purchase_date", "Invalid date format, use YYYY-MM-DD"
                )
    if manufacturer is not None:
        item.manufacturer = None if manufacturer == "" else manufacturer

    try:
        item.__post_init__()
    except Exception as e:  # noqa: BLE001
        return MCPResponseBuilder.validation_error_response("gear_item", str(e))

    # The service computes the changed-fields diff against the persisted state
    # and publishes GearItemUpdated with MCP provenance.
    saved_item = await gear_item_service.update(
        item,
        transaction=db_connection,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


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


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """Register every journal-domain MCP tool with the FastMCP server."""
    register_journal_read_tools(mcp)
    register_journal_entry_tools(mcp)
    register_journal_search_tools(mcp)
    register_journal_hierarchy_tools(mcp)
    register_activity_tools(mcp)
    register_journal_history_tools(mcp)
    register_journal_contact_tools(mcp)
    register_calendar_tools(mcp)
    register_journal_merge_tools(mcp)
    register_review_item_tools(mcp)
    register_outdoor_tools(mcp)
    register_daily_summary_tools(mcp)
    mcp.add_tool(create_template)
    mcp.add_tool(get_template)
    mcp.add_tool(get_journal_template)
    mcp.add_tool(search_templates)
    mcp.add_tool(update_template)
    mcp.add_tool(create_gear_item)
    mcp.add_tool(list_gear_items)
    mcp.add_tool(get_gear_item)
    mcp.add_tool(update_gear_item)
    mcp.add_tool(list_journal_tags)
    mcp.add_tool(update_journal_tag)
    mcp.add_tool(delete_journal_tag)
    mcp.add_tool(merge_journal_tag)
    register_journal_series_tools(mcp)
    register_journal_route_tools(mcp)
