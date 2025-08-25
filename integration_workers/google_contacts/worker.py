#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, UTC
from typing import Any

import structlog
from arq import run_worker
from arq.connections import RedisSettings
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Add core_shared to path for imports
sys.path.insert(0, "/core_shared")

# Import from the installed core_shared package
from core_shared.database.engine import create_session_factory
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

# Import worker-specific services
from google_auth_service import GoogleAuthService
from google_contacts_client import GoogleContactsAPIClient
from api_models import GooglePerson, ListConnectionsResponse

# Import outbox models from core_shared
from core_shared.models.outbox import OutboxEvent


class WorkerSettings(BaseSettings):
    """Configuration for Google Contacts worker."""

    # Database connection
    database_url: SecretStr

    # Redis connection
    redis_url: str = "redis://redis:6379"

    # Google API credentials
    google_client_id: str
    google_client_secret: SecretStr

    # Encryption key for tokens
    encryption_key: SecretStr

    # Worker configuration
    worker_id: str = "google-contacts-worker"
    log_level: str = "INFO"
    max_concurrent_jobs: int = 5

    class Config:
        env_file = ".env"


# Global settings instance
settings = WorkerSettings()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper())
    ),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Constants
SITE_USER_ID = 1  # Single-user system assumption - change if multi-user support needed


async def startup(ctx: dict[str, Any]) -> None:
    """
    Worker startup function.

    Initializes database session factory and other resources.
    """
    logger.info("Google Contacts worker starting up", worker_id=settings.worker_id)

    # Create database session factory
    session_factory = create_session_factory(settings.database_url.get_secret_value())
    ctx["session_factory"] = session_factory
    ctx["settings"] = settings

    logger.info("Google Contacts worker startup complete")


async def shutdown(ctx: dict[str, Any]) -> None:
    """
    Worker shutdown function.

    Cleans up resources when the worker shuts down.
    """
    logger.info("Google Contacts worker shutting down", worker_id=settings.worker_id)

    # Close database connections if needed
    session_factory = ctx.get("session_factory")
    if session_factory and hasattr(session_factory, "close"):
        await session_factory.close()

    logger.info("Google Contacts worker shutdown complete")


# Helper functions for sync logic

async def _determine_smart_sync_type(session: AsyncSession, google_account_email: str) -> str:
    """
    Determine whether to use full or incremental sync based on existing sync metadata.

    Args:
        session: Database session
        google_account_email: Google account email

    Returns:
        "full" or "incremental" based on existing sync state
    """
    # Check if we have a sync token for this account
    stmt = text("""
        SELECT sync_token
        FROM user_google_auth
        WHERE user_id = :user_id AND google_account_email = :email
        AND sync_token IS NOT NULL
    """)
    result = await session.execute(stmt, {"user_id": SITE_USER_ID, "email": google_account_email})
    sync_token = result.scalar()

    if sync_token:
        logger.info(
            "Found existing sync token, using incremental sync",
            google_account_email=google_account_email
        )
        return "incremental"
    else:
        logger.info(
            "No sync token found, using full sync",
            google_account_email=google_account_email
        )
        return "full"


async def _perform_full_sync(
    session: AsyncSession,
    client: GoogleContactsAPIClient,
    google_account_email: str,
    metrics: dict[str, Any]
) -> dict[str, Any]:
    """
    Perform a full sync of Google Contacts.

    Args:
        session: Database session
        client: Google Contacts API client
        google_account_email: Google account email
        metrics: Metrics dictionary to update

    Returns:
        Updated metrics
    """
    logger.info("Starting full sync", google_account_email=google_account_email)

    page_token = None
    total_processed = 0

    while True:
        # Fetch contacts from Google
        response = await client.list_connections(
            page_size=100,
            page_token=page_token
        )

        # Parse response
        contacts_response = ListConnectionsResponse(**response)

        if not contacts_response.connections:
            break

        # Batch serialize contacts for better performance
        try:
            # Pre-serialize all contacts in batch to avoid repeated model_dump() calls
            serialized_contacts = [
                (person, person.model_dump()) for person in contacts_response.connections
            ]
        except Exception as e:
            logger.error(
                "Failed to serialize contacts batch",
                google_account_email=google_account_email,
                batch_size=len(contacts_response.connections),
                error=str(e)
            )
            metrics["errors"] = metrics.get("errors", 0) + len(contacts_response.connections)
            continue

        # Process each contact using outbox pattern
        for google_person, contact_data in serialized_contacts:
            try:
                # Create outbox event for contact sync
                outbox_event = OutboxEvent.create_contact_sync_event(
                    contact_data=contact_data,
                    integration_source="google_contacts",
                    external_id=google_person.resource_name,
                    sync_type="created"
                )

                # Add to session (will be committed with transaction)
                session.add(outbox_event)

                total_processed += 1
                metrics["contacts_processed"] += 1

            except Exception as e:
                logger.error(
                    "Failed to create outbox event for contact",
                    google_account_email=google_account_email,
                    contact_resource_name=google_person.resource_name,
                    error=str(e)
                )
                metrics["errors"] = metrics.get("errors", 0) + 1

        # Check for next page
        page_token = contacts_response.next_page_token
        if not page_token:
            break

    # Save sync token if available
    if contacts_response.next_sync_token:
        await _save_sync_token(session, google_account_email, contacts_response.next_sync_token)

    logger.info(
        "Full sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed
    )

    return {"contacts_created": total_processed}


async def _perform_incremental_sync(
    session: AsyncSession,
    client: GoogleContactsAPIClient,
    google_account_email: str,
    metrics: dict[str, Any]
) -> dict[str, Any]:
    """
    Perform an incremental sync of Google Contacts using sync token.

    Args:
        session: Database session
        client: Google Contacts API client
        google_account_email: Google account email
        metrics: Metrics dictionary to update

    Returns:
        Updated metrics
    """
    logger.info("Starting incremental sync", google_account_email=google_account_email)

    # Get existing sync token
    stmt = text("""
        SELECT sync_token
        FROM user_google_auth
        WHERE user_id = :user_id AND google_account_email = :email
    """)
    result = await session.execute(stmt, {"user_id": SITE_USER_ID, "email": google_account_email})
    sync_token = result.scalar()

    if not sync_token:
        logger.warning(
            "No sync token found for incremental sync, falling back to full sync",
            google_account_email=google_account_email
        )
        return await _perform_full_sync(session, client, google_account_email, metrics)

    # Fetch changes since last sync
    response = await client.list_connections(sync_token=sync_token)
    contacts_response = ListConnectionsResponse(**response)

    total_processed = 0

    # Batch serialize contacts for better performance
    try:
        # Pre-serialize all contacts in batch to avoid repeated model_dump() calls
        serialized_contacts = [
            (person, person.model_dump()) for person in contacts_response.connections
        ]
    except Exception as e:
        logger.error(
            "Failed to serialize contacts batch",
            google_account_email=google_account_email,
            batch_size=len(contacts_response.connections),
            error=str(e)
        )
        return {"contacts_updated": 0, "errors": len(contacts_response.connections)}

    # Process changed contacts using outbox pattern
    for google_person, contact_data in serialized_contacts:
        try:
            # Create outbox event for contact sync
            outbox_event = OutboxEvent.create_contact_sync_event(
                contact_data=contact_data,
                integration_source="google_contacts",
                external_id=google_person.resource_name,
                sync_type="updated"
            )

            # Add to session (will be committed with transaction)
            session.add(outbox_event)

            total_processed += 1
            metrics["contacts_processed"] += 1

        except Exception as e:
            logger.error(
                "Failed to create outbox event for contact",
                google_account_email=google_account_email,
                contact_resource_name=google_person.resource_name,
                error=str(e)
            )
            metrics["errors"] = metrics.get("errors", 0) + 1

    # Save new sync token
    if contacts_response.next_sync_token:
        await _save_sync_token(session, google_account_email, contacts_response.next_sync_token)

    logger.info(
        "Incremental sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed
    )

    return {"contacts_updated": total_processed}


async def _save_sync_token(session: AsyncSession, google_account_email: str, sync_token: str) -> None:
    """
    Save sync token for future incremental syncs.

    Args:
        session: Database session
        google_account_email: Google account email
        sync_token: Sync token from Google API
    """
    stmt = text("""
        UPDATE user_google_auth
        SET sync_token = :sync_token, updated_at = :updated_at
        WHERE user_id = :user_id AND google_account_email = :email
    """)

    await session.execute(stmt, {
        "sync_token": sync_token,
        "updated_at": datetime.now(UTC),
        "user_id": SITE_USER_ID,
        "email": google_account_email
    })

    logger.info(
        "Saved sync token",
        google_account_email=google_account_email,
        sync_token_prefix=sync_token[:20] + "..." if len(sync_token) > 20 else sync_token
    )


async def sync_google_contacts(
    ctx: dict[str, Any],
    google_account_email: str,
    sync_type: str = "smart"
) -> dict[str, Any]:
    """
    Sync Google Contacts for a specific Google account.

    This is the main ARQ task that handles Google Contacts synchronization.
    It implements the smart sync strategy and idempotent operations.

    Args:
        ctx: ARQ context dictionary
        google_account_email: Google account email to sync
        sync_type: Type of sync - "full", "incremental", or "smart" (default)

    Returns:
        Task result dictionary with sync status and metrics
    """
    logger.info(
        "Starting Google Contacts sync task",
        google_account_email=google_account_email,
        sync_type=sync_type,
        worker_id=settings.worker_id
    )

    session_factory = ctx["session_factory"]

    # Initialize metrics
    metrics = {
        "contacts_processed": 0,
        "contacts_created": 0,
        "contacts_updated": 0,
        "contacts_deleted": 0,
        "sync_type_used": sync_type,
        "worker_id": settings.worker_id,
        "started_at": datetime.now(UTC).isoformat(),
    }

    try:
        # Use session-per-task pattern
        async with session_factory() as session:
            # Create services
            auth_service = GoogleAuthService(
                session=session,
                encryption_key=settings.encryption_key.get_secret_value(),
                google_client_id=settings.google_client_id,
                google_client_secret=settings.google_client_secret.get_secret_value(),
            )

            client = GoogleContactsAPIClient(
                auth_service=auth_service,
                google_account_email=google_account_email,
                google_client_id=settings.google_client_id,
                google_client_secret=settings.google_client_secret.get_secret_value(),
            )

            # Determine sync strategy
            if sync_type == "smart":
                sync_type = await _determine_smart_sync_type(session, google_account_email)
                logger.info(
                    "Smart sync determined sync type",
                    google_account_email=google_account_email,
                    determined_sync_type=sync_type
                )

            # Perform sync based on type
            if sync_type == "full":
                result = await _perform_full_sync(session, client, google_account_email, metrics)
            elif sync_type == "incremental":
                result = await _perform_incremental_sync(session, client, google_account_email, metrics)
            else:
                raise ValueError(f"Unknown sync type: {sync_type}")

            metrics.update(result)
            metrics["completed_at"] = datetime.now(UTC).isoformat()

            # Create sync completion event
            completion_event = OutboxEvent.create_sync_completed_event(
                integration_source="google_contacts",
                google_account_email=google_account_email,
                metrics=metrics
            )
            session.add(completion_event)

            # Commit all changes (contact events + completion event + sync token)
            await session.commit()

            logger.info(
                "Google Contacts sync task completed successfully",
                google_account_email=google_account_email,
                **metrics
            )

            return {
                "status": "success",
                "google_account_email": google_account_email,
                **metrics
            }

    except Exception as e:
        logger.error(
            "Google Contacts sync task failed",
            google_account_email=google_account_email,
            error=str(e),
            error_type=type(e).__name__,
        )

        # Return error result
        return {
            "status": "error",
            "google_account_email": google_account_email,
            "error": str(e),
            "error_type": type(e).__name__,
            "worker_id": settings.worker_id,
            "failed_at": datetime.now(UTC).isoformat(),
        }


# ARQ Worker Settings
class GoogleContactsWorkerSettings:
    """ARQ worker configuration."""

    # Task functions
    functions = [sync_google_contacts]

    # Worker lifecycle
    on_startup = startup
    on_shutdown = shutdown

    # Redis settings
    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Worker configuration
    max_jobs = settings.max_concurrent_jobs
    job_timeout = 600  # 10 minutes
    keep_result = 3600  # Keep results for 1 hour

    # Retry configuration
    max_tries = 5
    retry_delay = 60  # 1 minute base delay

    # Queue name
    queue_name = "google_contacts"


if __name__ == "__main__":
    # Run the worker
    logger.info("Starting Google Contacts ARQ worker", worker_id=settings.worker_id)
    run_worker(GoogleContactsWorkerSettings)
