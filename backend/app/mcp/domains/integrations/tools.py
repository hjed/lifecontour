"""
Integration domain MCP tools.

Provides AI access to integration status and management through MCP tools.
Each tool returns AI-friendly, contextual information about registered
integrations.
"""

import structlog
from core_shared.models.contacts.value_objects import Provenance
from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.immich.album_creation_service import (
    ImmichAlbumCreationService,
)
from app.core.integrations.immich.conflict_resolution_service import (
    ConflictResolutionAction,
    ImmichConflictResolutionService,
)
from app.core.integrations.registry.service import IntegrationRegistryService
from app.core.integrations.strava.athlete_mapping_service import (
    StravaAthleteMappingService,
)
from app.core.integrations.task_queue_service import TaskQueueService
from app.mcp.domains.integrations.contact_import_issue_tools import (
    register_contact_import_issue_tools,
)
from app.mcp.domains.integrations.contact_suggestion_tools import (
    register_contact_suggestion_tools,
)
from app.mcp.domains.integrations.schemas import (
    ImmichAlbumCreatedResponse,
    ImmichConflictListResponse,
    ImmichConflictMCP,
    ImmichConflictResolvedResponse,
    ImmichPhotoMCP,
    ImmichPhotoSearchResponse,
    IntegrationListResponse,
    IntegrationStatusMCP,
    StravaAthleteMappingListResponse,
    StravaAthleteMappingMCP,
    SyncSummaryMCP,
    SyncTriggeredResponse,
)
from app.mcp.shared.annotations import (
    EXTERNAL_ADDITIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_EXTERNAL,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_immich_album_creation_service,
    get_immich_conflict_resolution_service,
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
    register_contact_suggestion_tools(mcp)
    register_contact_import_issue_tools(mcp)

    @mcp.tool(annotations=READ_ONLY_EXTERNAL)
    @mcp_unified_error_handler("list_integrations", "integration")
    async def list_integrations(
        user_id: str = mcp_depends(get_current_user_id),
        connection: AsyncConnection = mcp_depends(get_async_connection),
        registry_service: IntegrationRegistryService = mcp_depends(
            get_integration_registry_service
        ),
    ) -> IntegrationListResponse:
        """
        List all registered integrations with their current status.

        Returns information about each connected integration including:
        - Connection status (connected/disconnected/error/token_expired)
        - Capabilities (contacts_sync, calendar_sync, activity_import)
        - Sync summary (last sync time, total syncs, error count)
        - Whether re-authentication or re-consent is needed

        Use this tool to check which integrations are available and their
        health status before performing integration-specific operations.
        """
        logger.info("MCP: Listing integrations", user_id=user_id)

        integrations = await registry_service.list_integrations(
            user_id=user_id, connection=connection
        )

        result = IntegrationListResponse(
            integrations=[
                IntegrationStatusMCP(
                    id=info.id,
                    name=info.name,
                    status=info.status,
                    capabilities=list(info.capabilities),
                    sync_summary=SyncSummaryMCP(
                        last_sync_time=(
                            info.sync_summary.last_sync_time.isoformat()
                            if info.sync_summary.last_sync_time
                            else None
                        ),
                        sync_count=info.sync_summary.sync_count,
                        error_count=info.sync_summary.error_count,
                    ),
                    needs_reauth=info.needs_reauth,
                    needs_reconsent=info.needs_reconsent,
                )
                for info in integrations
            ],
            total_count=len(integrations),
            summary=_build_summary(integrations),
        )

        logger.info(
            "MCP: Integrations listed",
            user_id=user_id,
            integration_count=len(integrations),
        )

        return result

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

    @mcp.tool(annotations=EXTERNAL_ADDITIVE_WRITE)
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
    ) -> SyncTriggeredResponse:
        """
        Trigger a sync for a specific integration.

        Args:
            integration_id: The ID of the integration ('strava', 'immich', 'google_calendar', or 'google_contacts').
            sync_type: The type of sync to perform (e.g., 'smart', 'full'). Defaults to 'smart'.
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

        return SyncTriggeredResponse(
            integration_id=integration_id, job_id=job_id, status="queued"
        )

    @mcp.tool(annotations=READ_ONLY)
    @mcp_unified_error_handler("get_strava_athlete_mappings", "integration")
    async def get_strava_athlete_mappings(
        contact_id: int | None = None,
        strava_athlete_id: str | None = None,
        user_id: str = mcp_depends(get_current_user_id),
        mapping_service: StravaAthleteMappingService = mcp_depends(
            get_strava_athlete_mapping_service
        ),
    ) -> StravaAthleteMappingListResponse:
        """
        Get Strava athlete-to-contact mappings.

        You can optionally filter the results by providing a `contact_id` or `strava_athlete_id`.
        If no filters are provided, all mappings for the user are returned.

        Args:
            contact_id: Filter mappings by the internal contact ID.
            strava_athlete_id: Filter mappings by the Strava athlete ID.
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

        return StravaAthleteMappingListResponse(
            mappings=[
                StravaAthleteMappingMCP(
                    strava_athlete_id=m.strava_athlete_id,
                    strava_athlete_name=m.strava_athlete_name,
                    contact_id=m.contact_id,
                )
                for m in filtered_mappings
            ],
            total_count=len(filtered_mappings),
        )

    @mcp.tool(annotations=READ_ONLY)
    @mcp_unified_error_handler("list_immich_conflicts", "integration")
    async def list_immich_conflicts(
        user_id: str = mcp_depends(get_current_user_id),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> ImmichConflictListResponse:
        """
        List unresolved Immich synchronisation conflicts.

        When Immich contacts cannot be automatically matched to a single
        local contact (e.g. multiple contacts share the same name), a
        conflict is created. This tool returns the list of unresolved
        conflicts that need manual resolution.

        Each conflict includes:
        - conflict id
        - external_entity_id: the Immich person UUID
        - external_entity_name: the person's name in Immich
        - candidate_contact_ids: list of local contact IDs that may match
        - status: always 'unresolved' for pending conflicts
        """
        from core_shared.repositories.pending_entity_mapping_repository import (
            PendingEntityMappingRepository,
        )

        logger.info("MCP: Listing Immich conflicts", user_id=user_id)

        repo = PendingEntityMappingRepository(connection)
        conflicts = await repo.find_unresolved(
            user_id=user_id, integration_source="immich"
        )

        result = ImmichConflictListResponse(
            conflicts=[
                ImmichConflictMCP(
                    id=c["id"],
                    external_entity_id=c["external_entity_id"],
                    external_entity_name=c["external_entity_name"],
                    candidate_contact_ids=c["candidate_contact_ids"],
                    status=c["status"],
                    created_at=(
                        c["created_at"].isoformat() if c["created_at"] else None
                    ),
                )
                for c in conflicts
            ],
            total_count=len(conflicts),
        )

        logger.info(
            "MCP: Immich conflicts listed",
            user_id=user_id,
            conflict_count=len(conflicts),
        )

        return result

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @mcp_unified_error_handler("resolve_immich_conflict", "integration")
    async def resolve_immich_conflict(
        conflict_id: int,
        action: str,
        contact_id: int | None = None,
        user_id: str = mcp_depends(get_current_user_id),
        connection: AsyncConnection = mcp_depends(get_async_connection),
        service: ImmichConflictResolutionService = mcp_depends(
            get_immich_conflict_resolution_service
        ),
    ) -> ImmichConflictResolvedResponse:
        """
        Resolve an Immich synchronisation conflict.

        Links an Immich person to a local contact (action='link') or creates
        a new contact from the Immich person's name (action='create').

        Args:
            conflict_id: The ID of the conflict to resolve.
            action: Either 'link' (to link to an existing contact) or
                    'create' (to create a new contact from the Immich name).
            contact_id: Required when action='link'. The ID of the local
                        contact to link the Immich person to.
        """
        logger.info(
            "MCP: Resolving Immich conflict",
            user_id=user_id,
            conflict_id=conflict_id,
            action=action,
        )

        if action not in ("link", "create"):
            raise ValueError(f"Invalid action '{action}'. Must be 'link' or 'create'.")

        # The @transactional service owns the commit (see AGENTS.md "Transactions").
        resolved = await service.resolve(
            conflict_id,
            ConflictResolutionAction(action),
            contact_id,
            user_id=user_id,
            provenance=Provenance.MCP,
            transaction=connection,
        )
        resolved_contact_id = resolved.contact_id

        result = ImmichConflictResolvedResponse(
            conflict_id=conflict_id,
            action=ConflictResolutionAction(action),
            contact_id=resolved_contact_id,
            status="resolved",
        )

        logger.info(
            "MCP: Immich conflict resolved",
            user_id=user_id,
            conflict_id=conflict_id,
            action=action,
            contact_id=resolved_contact_id,
        )

        return result

    @mcp.tool(annotations=READ_ONLY_EXTERNAL)
    @mcp_unified_error_handler("search_immich_photos_for_journal", "integration")
    async def search_immich_photos_for_journal(
        journal_id: int,
        user_id: str = mcp_depends(get_current_user_id),
        service: ImmichAlbumCreationService = mcp_depends(
            get_immich_album_creation_service
        ),
    ) -> ImmichPhotoSearchResponse:
        """
        Find Immich photos taken within a journal's date range.

        Searches the connected Immich instance for photos whose capture time
        falls within the journal's event date range (expanded to full days in
        the user's timezone). Use this before creating an album to see which
        photos would be included.

        Args:
            journal_id: The ID of the journal whose date range to search.
        """
        logger.info(
            "MCP: Searching Immich photos for journal",
            user_id=user_id,
            journal_id=journal_id,
        )

        photos = await service.search_photos(journal_id, user_id)

        return ImmichPhotoSearchResponse(
            journal_id=journal_id,
            photos=[
                ImmichPhotoMCP(
                    asset_id=p.asset_id,
                    original_file_name=p.original_file_name,
                    taken_at=p.taken_at,
                )
                for p in photos
            ],
            total_count=len(photos),
        )

    @mcp.tool(annotations=EXTERNAL_ADDITIVE_WRITE)
    @mcp_unified_error_handler("create_immich_album_for_journal", "integration")
    async def create_immich_album_for_journal(
        journal_id: int,
        create_shared_link: bool = False,
        exclude_asset_ids: list[str] | None = None,
        user_id: str = mcp_depends(get_current_user_id),
        service: ImmichAlbumCreationService = mcp_depends(
            get_immich_album_creation_service
        ),
    ) -> ImmichAlbumCreatedResponse:
        """
        Create an Immich album from a journal's date range.

        Searches for photos in the journal's date range and creates an Immich
        album from them, named after the journal. All matching photos are
        included by default; pass ``exclude_asset_ids`` to leave some out. The
        new album is linked back to the journal (which marks it as a
        PHOTO_ALBUM). Fails if the journal already has a linked album.

        Args:
            journal_id: The ID of the journal to create an album for.
            create_shared_link: Whether to create a public shared link.
            exclude_asset_ids: Immich asset IDs to omit from the album.
        """
        logger.info(
            "MCP: Creating Immich album for journal",
            user_id=user_id,
            journal_id=journal_id,
            create_shared_link=create_shared_link,
        )

        photos = await service.search_photos(journal_id, user_id)
        excluded = set(exclude_asset_ids or [])
        asset_ids = [p.asset_id for p in photos if p.asset_id not in excluded]

        # ``create_album`` owns its own unit of work, committing the album link
        # + sync metadata writes before the response (the MCP tool, like a
        # controller, must not open a transaction itself).
        created = await service.create_album(
            journal_id,
            user_id,
            asset_ids=asset_ids,
            create_shared_link=create_shared_link,
        )

        return ImmichAlbumCreatedResponse(
            journal_id=created.journal_id,
            album_id=created.album_id,
            asset_count=created.asset_count,
            shared_link_url=created.shared_link_url,
            status="created",
        )
