"""
Integration domain MCP tools.

Provides AI access to integration status and management through MCP tools.
Each tool returns AI-friendly, contextual information about registered
integrations.
"""

import json

import structlog
from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.registry.service import IntegrationRegistryService
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_integration_registry_service,
    mcp_depends,
)

logger = structlog.get_logger()


def register_integration_tools(mcp: FastMCP[None]) -> None:
    """
    Register integration-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("list_integrations", "integration")
    async def list_integrations(
        user_id: str = mcp_depends(get_current_user_id),
        connection: AsyncConnection = mcp_depends(get_async_connection),
        registry_service: IntegrationRegistryService = mcp_depends(
            get_integration_registry_service
        ),
    ) -> str:
        """
        List all registered integrations with their current status.

        Returns information about each connected integration including:
        - Connection status (connected/disconnected/error/token_expired)
        - Capabilities (contacts_sync, calendar_sync, activity_import)
        - Sync summary (last sync time, total syncs, error count)
        - Whether re-authentication or re-consent is needed

        Use this tool to check which integrations are available and their
        health status before performing integration-specific operations.

        Returns:
            JSON string containing integration list with status and capabilities
        """
        logger.info("MCP: Listing integrations", user_id=user_id)

        integrations = await registry_service.list_integrations(
            user_id=user_id, connection=connection
        )

        result = {
            "integrations": [
                {
                    "id": info.id,
                    "name": info.name,
                    "status": info.status.value,
                    "capabilities": [c.value for c in info.capabilities],
                    "sync_summary": {
                        "last_sync_time": (
                            info.sync_summary.last_sync_time.isoformat()
                            if info.sync_summary.last_sync_time
                            else None
                        ),
                        "sync_count": info.sync_summary.sync_count,
                        "error_count": info.sync_summary.error_count,
                    },
                    "needs_reauth": info.needs_reauth,
                    "needs_reconsent": info.needs_reconsent,
                }
                for info in integrations
            ],
            "total_count": len(integrations),
            "summary": _build_summary(integrations),
        }

        logger.info(
            "MCP: Integrations listed",
            user_id=user_id,
            integration_count=len(integrations),
        )

        return json.dumps(result, indent=2)

    def _build_summary(integrations: list) -> str:  # type: ignore[type-arg]
        """Build an AI-friendly summary of integration states."""
        if not integrations:
            return "No integrations registered."

        connected = sum(1 for i in integrations if i.status.value == "connected")
        total = len(integrations)
        parts = [f"{connected}/{total} integrations connected"]

        needs_action = [
            i.name for i in integrations if i.needs_reauth or i.needs_reconsent
        ]
        if needs_action:
            parts.append(f"Action required for: {', '.join(needs_action)}")

        errored = [i.name for i in integrations if i.status.value == "error"]
        if errored:
            parts.append(f"Errors: {', '.join(errored)}")

        return ". ".join(parts) + "."
