"""MCP tools for activity templates — the standard canyons, caves and climbs."""

from typing import Annotated

from core_shared.models.journals import (
    ActivityTemplate,
    CanyonType,
    ClimbingType,
    TemplatePitch,
    TemplateType,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.activity_template_service import (
    ActivityTemplateService,
)
from app.mcp.domains.journals.converters import (
    ActivityTemplateMCPConverter,
)
from app.mcp.domains.journals.schemas import (
    JournalTemplateMCPResponse,
    TemplatePitchInput,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
)

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_template_service,
    get_async_connection,
    get_current_user_id,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

# The template fields ``create_template`` and ``update_template`` share, declared
# once: the two signatures repeat them verbatim otherwise, and a field's
# description has to read the same on both tools or the same argument is
# documented two ways.
Region = Annotated[str | None, Field(default=None, description="Region")]
Description = Annotated[str | None, Field(default=None, description="Description")]
FrenchGrade = Annotated[str | None, Field(default=None, description="French grade")]
CanyonTypeArg = Annotated[
    CanyonType | None, Field(default=None, description="Canyon type")
]
WaterGaugeName = Annotated[
    str | None, Field(default=None, description="Water gauge name")
]
IsVertical = Annotated[bool | None, Field(default=None, description="Is vertical")]
IsHorizontal = Annotated[bool | None, Field(default=None, description="Is horizontal")]
ClimbingTypeArg = Annotated[
    ClimbingType | None, Field(default=None, description="Climbing type")
]
Grade = Annotated[int | None, Field(default=None, description="Grade")]
Length = Annotated[int | None, Field(default=None, description="Length in metres")]
Pitches = Annotated[
    list[TemplatePitchInput] | None,
    Field(default=None, description="Pitches in order; pitch_number is required"),
]


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_template", "journal")
async def create_template(
    name: Annotated[str, Field(description="Template name")],
    template_type: Annotated[TemplateType, Field(description="Type of template")],
    region: Region = None,
    description: Description = None,
    french_grade: FrenchGrade = None,
    canyon_type: CanyonTypeArg = None,
    water_gauge_name: WaterGaugeName = None,
    is_vertical: IsVertical = None,
    is_horizontal: IsHorizontal = None,
    climbing_type: ClimbingTypeArg = None,
    grade: Grade = None,
    length: Length = None,
    pitches: Pitches = None,
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
    region: Region = None,
    description: Description = None,
    french_grade: FrenchGrade = None,
    canyon_type: CanyonTypeArg = None,
    water_gauge_name: WaterGaugeName = None,
    is_vertical: IsVertical = None,
    is_horizontal: IsHorizontal = None,
    climbing_type: ClimbingTypeArg = None,
    grade: Grade = None,
    length: Length = None,
    pitches: Pitches = None,
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


def register_template_tools(mcp: FastMCP[None]) -> None:
    """Register the templates MCP tools with the FastMCP server."""
    mcp.add_tool(create_template)
    mcp.add_tool(get_template)
    mcp.add_tool(get_journal_template)
    mcp.add_tool(search_templates)
    mcp.add_tool(update_template)
