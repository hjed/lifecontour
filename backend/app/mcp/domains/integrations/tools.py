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
from app.core.integrations.strava.athlete_mapping_service import (
    StravaAthleteMappingService,
)
from app.core.integrations.task_queue_service import TaskQueueService
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_integration_registry_service,
    get_strava_athlete_mapping_service,
    get_task_queue_service,
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

    @mcp.tool
    @mcp_unified_error_handler("trigger_sync", "integration")
    async def trigger_sync(
        integration_id: str,
        user_id: str = mcp_depends(get_current_user_id),
        task_queue_service: TaskQueueService = mcp_depends(get_task_queue_service),
        integration_registry_service: IntegrationRegistryService = mcp_depends(
            get_integration_registry_service
        ),
        connection: AsyncConnection = mcp_depends(get_async_connection),
        sync_type: str = "smart",
    ) -> str:
        """
        Trigger a sync for a specific integration.

        Args:
            integration_id: The ID of the integration ('strava' or 'immich').
            sync_type: The type of sync to perform (e.g., 'smart', 'full'). Defaults to 'smart'.

        Returns:
            JSON string containing the job ID, integration_id, and status of the newly enqueued sync job.
        """
        logger.info(
            "MCP: Triggering sync",
            user_id=user_id,
            integration_id=integration_id,
            sync_type=sync_type,
        )

        job_id = None
        if integration_id == "strava":
            from app.core.integrations.registry.models import IntegrationStatus

            integrations = await integration_registry_service.list_integrations(
                user_id=user_id, connection=connection
            )
            strava_info = next(
                (info for info in integrations if info.id == "strava"), None
            )

            if not strava_info or strava_info.status != IntegrationStatus.CONNECTED:
                raise ValueError(
                    "Cannot trigger sync: Strava integration is not connected."
                )

            job_id = await task_queue_service.enqueue_strava_sync(
                user_id=user_id, sync_type=sync_type
            )
        elif integration_id == "immich":
            from app.core.integrations.registry.models import IntegrationStatus

            integrations = await integration_registry_service.list_integrations(
                user_id=user_id, connection=connection
            )
            immich_info = next(
                (info for info in integrations if info.id == "immich"), None
            )

            if not immich_info or immich_info.status != IntegrationStatus.CONNECTED:
                raise ValueError(
                    "Cannot trigger sync: Immich integration is not connected."
                )

            job_id = await task_queue_service.enqueue_immich_sync(
                user_id=user_id, sync_type=sync_type
            )
        elif integration_id == "google_calendar":
            # For Google integrations we normally need google_account_email.
            # Assuming 'primary' or user's email if not provided directly via another way
            # Since MCP might not have the account email readily, it's a limitation for now
            # Actually task queue service takes google_account_email as first param
            raise ValueError(
                "Triggering sync for google_calendar requires account email which is not supported yet."
            )
        elif integration_id == "google_contacts":
            raise ValueError(
                "Triggering sync for google_contacts requires account email which is not supported yet."
            )
        else:
            raise ValueError(f"Unsupported integration_id: {integration_id}")

        result = {
            "integration_id": integration_id,
            "job_id": job_id,
            "status": "queued",
        }

        return json.dumps(result, indent=2)

    @mcp.tool
    @mcp_unified_error_handler("get_strava_athlete_mappings", "integration")
    async def get_strava_athlete_mappings(
        contact_id: int | None = None,
        strava_athlete_id: str | None = None,
        user_id: str = mcp_depends(get_current_user_id),
        mapping_service: StravaAthleteMappingService = mcp_depends(
            get_strava_athlete_mapping_service
        ),
    ) -> str:
        """
        Get Strava athlete-to-contact mappings.

        You can optionally filter the results by providing a `contact_id` or `strava_athlete_id`.
        If no filters are provided, all mappings for the user are returned.

        Args:
            contact_id: Filter mappings by the internal contact ID.
            strava_athlete_id: Filter mappings by the Strava athlete ID.

        Returns:
            JSON string containing the athlete mappings.
        """
        logger.info(
            "MCP: Getting Strava athlete mappings",
            user_id=user_id,
            contact_id=contact_id,
            strava_athlete_id=strava_athlete_id,
        )

        all_mappings = await mapping_service.get_all_mappings(user_id=user_id)

        # Apply filters
        filtered_mappings = all_mappings
        if contact_id is not None:
            filtered_mappings = [
                m for m in filtered_mappings if m.contact_id == contact_id
            ]
        if strava_athlete_id is not None:
            filtered_mappings = [
                m for m in filtered_mappings if m.strava_athlete_id == strava_athlete_id
            ]

        result = {
            "mappings": [
                {
                    "strava_athlete_id": m.strava_athlete_id,
                    "strava_athlete_name": m.strava_athlete_name,
                    "contact_id": m.contact_id,
                }
                for m in filtered_mappings
            ],
            "total_count": len(filtered_mappings),
        }

        return json.dumps(result, indent=2)
