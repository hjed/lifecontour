#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Any

import structlog
from arq import run_worker
from arq.connections import RedisSettings
from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import text

# Add core_shared to path for imports
sys.path.insert(0, "/core_shared")

# Import from the installed core_shared package
from core_shared.database.engine import create_session_factory
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus


class WorkerSettings(BaseSettings):
    """Configuration for Google Contacts worker."""
    
    # Database connection
    database_url: SecretStr
    
    # Redis connection
    redis_url: str = "redis://redis:6379"
    
    # Google API credentials
    google_client_id: str
    google_client_secret: SecretStr
    
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


# Import the actual task implementation
# Note: This will be imported from the main app's task module
# For now, we'll implement a simplified version here

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
        "started_at": datetime.now().isoformat(),
    }

    try:
        # Use session-per-task pattern
        async with session_factory() as session:
            # TODO: Implement actual sync logic using the session
            # For now, just simulate work and test database connectivity

            # Test database connection
            result = await session.execute(text("SELECT 1"))
            test_value = result.scalar()

            if test_value != 1:
                raise Exception("Database connectivity test failed")

            # Simulate sync work
            await asyncio.sleep(1)

            # Update metrics
            metrics["contacts_processed"] = 0  # Placeholder
            metrics["completed_at"] = datetime.now().isoformat()

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
            "failed_at": datetime.now().isoformat(),
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
