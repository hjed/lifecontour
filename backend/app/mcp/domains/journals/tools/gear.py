"""MCP tools for tracked gear items (ropes, harnesses, helmets and the like)."""

from datetime import date
from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    GearItem,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.gear_item_service import GearItemService
from app.mcp.domains.journals.converters import (
    GearItemMCPConverter,
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
    get_async_connection,
    get_current_user_id,
    get_gear_item_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


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


def register_gear_tools(mcp: FastMCP[None]) -> None:
    """Register the gear MCP tools with the FastMCP server."""
    mcp.add_tool(create_gear_item)
    mcp.add_tool(list_gear_items)
    mcp.add_tool(get_gear_item)
    mcp.add_tool(update_gear_item)
