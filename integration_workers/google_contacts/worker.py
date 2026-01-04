#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

import logging
import sys
from datetime import UTC, datetime
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
from api_models import ListConnectionsResponse
from core_shared.database.engine import create_session_factory

# Import outbox models from core_shared
from core_shared.models.outbox import OutboxEvent
from core_shared.models.sync_metadata import SyncStatus

# Import worker-specific services
from google_auth_service import GoogleAuthService
from google_contacts_client import GoogleContactsAPIClient


class WorkerSettings(BaseSettings):
    """Configuration for Google Contacts worker."""

    model_config = {"env_file": ".env"}

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


# Global settings instance
settings = WorkerSettings()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
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


async def find_contacts_to_push(
    session: AsyncSession, integration_source: str = "google_contacts"
) -> list[dict[str, Any]]:
    """
    Find contacts that need to be pushed to Google.

    Identifies two types of contacts:
    1. Newly created contacts (no sync metadata entry)
    2. Updated contacts (updated_at > last_synced_at)

    Args:
        session: Database session
        integration_source: Integration source name (default: "google_contacts")

    Returns:
        List of contact dictionaries with sync action ("create" or "update")
    """
    # Query to find contacts that need to be pushed
    # This uses a LEFT JOIN to find both:
    # - Contacts without sync metadata (newly created locally)
    # - Contacts updated after last sync
    stmt = text("""
        SELECT
            c.id,
            c.first_name,
            c.last_name,
            c.middle_name,
            c.nick_name,
            c.is_favourite,
            c.created_at,
            c.updated_at,
            sm.external_id,
            sm.last_synced_at,
            sm.version_hash,
            CASE
                WHEN sm.id IS NULL THEN 'create'
                WHEN c.updated_at > sm.last_synced_at THEN 'update'
                ELSE NULL
            END as sync_action
        FROM contacts c
        LEFT JOIN sync_metadata sm ON
            c.id = sm.internal_id AND
            sm.integration_source = :integration_source
        WHERE
            -- Either no sync metadata (new contact)
            sm.id IS NULL
            -- Or contact updated after last sync
            OR c.updated_at > sm.last_synced_at
        ORDER BY c.updated_at ASC
    """)

    result = await session.execute(stmt, {"integration_source": integration_source})
    rows = result.fetchall()

    contacts = []
    for row in rows:
        contact_dict = {
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "middle_name": row.middle_name,
            "nick_name": row.nick_name,
            "is_favourite": row.is_favourite,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "external_id": row.external_id,
            "last_synced_at": row.last_synced_at,
            "version_hash": row.version_hash,
            "sync_action": row.sync_action,
        }
        contacts.append(contact_dict)

    logger.info(
        "Found contacts to push",
        integration_source=integration_source,
        total_contacts=len(contacts),
        new_contacts=sum(1 for c in contacts if c["sync_action"] == "create"),
        updated_contacts=sum(1 for c in contacts if c["sync_action"] == "update"),
    )

    return contacts


async def _load_full_contact(session: AsyncSession, contact_id: int) -> dict[str, Any]:
    """
    Load full contact data including methods, addresses, and notes.

    Args:
        session: Database session
        contact_id: Contact ID

    Returns:
        Dictionary with full contact data
    """
    # Load contact methods
    methods_stmt = text("""
        SELECT id, method_type, value, label, is_primary
        FROM contact_methods
        WHERE contact_id = :contact_id
        ORDER BY is_primary DESC, id ASC
    """)
    methods_result = await session.execute(methods_stmt, {"contact_id": contact_id})
    methods_rows = methods_result.fetchall()
    methods = [
        {
            "id": row.id,
            "method_type": row.method_type,
            "value": row.value,
            "label": row.label,
            "is_primary": row.is_primary,
        }
        for row in methods_rows
    ]

    # Load contact addresses
    addresses_stmt = text("""
        SELECT id, label, street_line_1, street_line_2, locality,
               region, postal_code, country_code, is_primary
        FROM contact_addresses
        WHERE contact_id = :contact_id
        ORDER BY is_primary DESC, id ASC
    """)
    addresses_result = await session.execute(addresses_stmt, {"contact_id": contact_id})
    addresses_rows = addresses_result.fetchall()
    addresses = [
        {
            "id": row.id,
            "label": row.label,
            "street_line_1": row.street_line_1,
            "street_line_2": row.street_line_2,
            "locality": row.locality,
            "region": row.region,
            "postal_code": row.postal_code,
            "country_code": row.country_code,
            "is_primary": row.is_primary,
        }
        for row in addresses_rows
    ]

    # Load contact notes
    notes_stmt = text("""
        SELECT id, content
        FROM contact_notes
        WHERE contact_id = :contact_id
        ORDER BY created_at DESC
    """)
    notes_result = await session.execute(notes_stmt, {"contact_id": contact_id})
    notes_rows = notes_result.fetchall()
    notes = [{"id": row.id, "content": row.content} for row in notes_rows]

    return {"methods": methods, "addresses": addresses, "notes": notes}


def _transform_contact_to_google_person(contact: dict[str, Any]) -> dict[str, Any]:
    """
    Transform internal contact format to Google People API Person format.

    Args:
        contact: Contact dictionary with full data (including methods, addresses, notes)

    Returns:
        Dictionary in Google People API Person format
    """
    person_data: dict[str, Any] = {}

    # Transform names
    names = []
    name_data: dict[str, Any] = {}
    if contact.get("first_name"):
        name_data["givenName"] = contact["first_name"]
    if contact.get("last_name"):
        name_data["familyName"] = contact["last_name"]
    if contact.get("middle_name"):
        name_data["middleName"] = contact["middle_name"]

    if name_data:
        names.append(name_data)
    if names:
        person_data["names"] = names

    # Transform nicknames
    if contact.get("nick_name"):
        person_data["nicknames"] = [{"value": contact["nick_name"]}]

    # Transform contact methods (emails and phones)
    methods = contact.get("methods", [])
    email_addresses = []
    phone_numbers = []

    for method in methods:
        if method["method_type"] == "email":
            email_data: dict[str, Any] = {"value": method["value"]}
            if method.get("label"):
                email_data["type"] = method["label"]
            if method.get("is_primary"):
                email_data["metadata"] = {"primary": True}
            email_addresses.append(email_data)
        elif method["method_type"] == "phone":
            phone_data: dict[str, Any] = {"value": method["value"]}
            if method.get("label"):
                phone_data["type"] = method["label"]
            if method.get("is_primary"):
                phone_data["metadata"] = {"primary": True}
            phone_numbers.append(phone_data)

    if email_addresses:
        person_data["emailAddresses"] = email_addresses
    if phone_numbers:
        person_data["phoneNumbers"] = phone_numbers

    # Transform addresses
    addresses = contact.get("addresses", [])
    if addresses:
        google_addresses = []
        for addr in addresses:
            addr_data: dict[str, Any] = {}
            if addr.get("street_line_1"):
                addr_data["streetAddress"] = addr["street_line_1"]
            if addr.get("street_line_2"):
                # Append to street address
                if "streetAddress" in addr_data:
                    addr_data["streetAddress"] += f"\n{addr['street_line_2']}"
                else:
                    addr_data["streetAddress"] = addr["street_line_2"]
            if addr.get("locality"):
                addr_data["city"] = addr["locality"]
            if addr.get("region"):
                addr_data["region"] = addr["region"]
            if addr.get("postal_code"):
                addr_data["postalCode"] = addr["postal_code"]
            if addr.get("country_code"):
                addr_data["countryCode"] = addr["country_code"]
            if addr.get("label"):
                addr_data["type"] = addr["label"]
            if addr.get("is_primary"):
                addr_data["metadata"] = {"primary": True}

            if addr_data:
                google_addresses.append(addr_data)

        if google_addresses:
            person_data["addresses"] = google_addresses

    # Transform notes to biographies
    notes = contact.get("notes", [])
    if notes:
        # Combine all notes into a single biography
        combined_notes = "\n\n".join(note["content"] for note in notes)
        person_data["biographies"] = [{"value": combined_notes, "contentType": "TEXT_PLAIN"}]

    return person_data


async def push_contacts_to_google(
    session: AsyncSession,
    client: GoogleContactsAPIClient,
    contacts: list[dict[str, Any]],
    google_account_email: str,
) -> dict[str, Any]:
    """
    Push local contacts to Google.

    Args:
        session: Database session
        client: Google Contacts API client
        contacts: List of contacts to push (from find_contacts_to_push)
        google_account_email: Google account email

    Returns:
        Dictionary with push metrics
    """
    from googleapiclient.errors import HttpError

    metrics = {
        "pushed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0,
        "conflict_count": 0,
    }

    for contact in contacts:
        try:
            # Load full contact data (methods, addresses, notes)
            full_contact_data = await _load_full_contact(session, contact["id"])
            contact.update(full_contact_data)

            # Transform to Google Person format
            person_data = _transform_contact_to_google_person(contact)

            if contact["sync_action"] == "create":
                # Create new contact in Google
                logger.info(
                    "Creating contact in Google",
                    contact_id=contact["id"],
                    google_account_email=google_account_email,
                )

                result = await client.create_contact(person_data)

                # Update sync metadata
                await _upsert_sync_metadata(
                    session=session,
                    internal_id=contact["id"],
                    external_id=result["resourceName"],
                    etag=result.get("etag"),
                    integration_source="google_contacts",
                )

                metrics["created_count"] += 1
                metrics["pushed_count"] += 1

                logger.info(
                    "Successfully created contact in Google",
                    contact_id=contact["id"],
                    resource_name=result["resourceName"],
                )

            elif contact["sync_action"] == "update":
                # Update existing contact in Google
                logger.info(
                    "Updating contact in Google",
                    contact_id=contact["id"],
                    external_id=contact["external_id"],
                    google_account_email=google_account_email,
                )

                # Get current ETag from sync metadata
                etag = contact.get("version_hash")

                result = await client.update_contact(
                    resource_name=contact["external_id"],
                    contact_data=person_data,
                    etag=etag,
                )

                # Update sync metadata with new ETag
                await _upsert_sync_metadata(
                    session=session,
                    internal_id=contact["id"],
                    external_id=result["resourceName"],
                    etag=result.get("etag"),
                    integration_source="google_contacts",
                )

                metrics["updated_count"] += 1
                metrics["pushed_count"] += 1

                logger.info(
                    "Successfully updated contact in Google",
                    contact_id=contact["id"],
                    resource_name=result["resourceName"],
                )

        except HttpError as e:
            # Handle ETag conflicts (400 with failedPrecondition)
            error_content = e.content.decode() if isinstance(e.content, bytes) else str(e.content)
            if e.resp.status == 400 and "failed_precondition" in error_content.lower():
                logger.warning(
                    "ETag conflict detected, skipping contact",
                    contact_id=contact["id"],
                    external_id=contact.get("external_id"),
                    error=str(e),
                )
                metrics["conflict_count"] += 1
                metrics["error_count"] += 1
            else:
                logger.error(
                    "Failed to push contact to Google",
                    contact_id=contact["id"],
                    sync_action=contact["sync_action"],
                    error=str(e),
                    status_code=e.resp.status,
                )
                metrics["error_count"] += 1

        except Exception as e:
            logger.error(
                "Unexpected error pushing contact to Google",
                contact_id=contact["id"],
                sync_action=contact["sync_action"],
                error=str(e),
            )
            metrics["error_count"] += 1

    logger.info(
        "Completed pushing contacts to Google",
        google_account_email=google_account_email,
        **metrics,
    )

    return metrics


async def _upsert_sync_metadata(
    session: AsyncSession,
    internal_id: int,
    external_id: str,
    etag: str | None,
    integration_source: str,
) -> None:
    """
    Upsert sync metadata after successful push.

    Args:
        session: Database session
        internal_id: Internal contact ID
        external_id: Google resource name
        etag: Google ETag
        integration_source: Integration source name
    """
    # Calculate version hash from ETag
    version_hash = etag if etag else ""

    now = datetime.now(UTC)

    stmt = text("""
        INSERT INTO sync_metadata
            (internal_id, integration_source, external_id, last_synced_at,
             version_hash, sync_status, created_at, updated_at)
        VALUES
            (:internal_id, :integration_source, :external_id, :last_synced_at,
             :version_hash, :sync_status, :created_at, :updated_at)
        ON CONFLICT (integration_source, external_id)
        DO UPDATE SET
            internal_id = EXCLUDED.internal_id,
            last_synced_at = EXCLUDED.last_synced_at,
            version_hash = EXCLUDED.version_hash,
            sync_status = EXCLUDED.sync_status,
            updated_at = EXCLUDED.updated_at
    """)

    await session.execute(
        stmt,
        {
            "internal_id": internal_id,
            "integration_source": integration_source,
            "external_id": external_id,
            "last_synced_at": now,
            "version_hash": version_hash,
            "sync_status": SyncStatus.SUCCESS.value,
            "created_at": now,
            "updated_at": now,
        },
    )


async def _determine_smart_sync_type(
    session: AsyncSession, google_account_email: str
) -> str:
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
    result = await session.execute(
        stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
    )
    sync_token = result.scalar()

    if sync_token:
        logger.info(
            "Found existing sync token, using incremental sync",
            google_account_email=google_account_email,
        )
        return "incremental"
    else:
        logger.info(
            "No sync token found, using full sync",
            google_account_email=google_account_email,
        )
        return "full"


async def _perform_full_sync(
    session: AsyncSession,
    client: GoogleContactsAPIClient,
    google_account_email: str,
    metrics: dict[str, Any],
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
        response = await client.list_connections(page_size=100, page_token=page_token)

        # Parse response
        contacts_response = ListConnectionsResponse(**response)

        if not contacts_response.connections:
            break

        # Batch serialize contacts for better performance
        try:
            # Pre-serialize all contacts in batch to avoid repeated model_dump() calls
            serialized_contacts = [
                (person, person.model_dump())
                for person in contacts_response.connections
            ]
        except Exception as e:
            logger.error(
                "Failed to serialize contacts batch",
                google_account_email=google_account_email,
                batch_size=len(contacts_response.connections),
                error=str(e),
            )
            metrics["errors"] = metrics.get("errors", 0) + len(
                contacts_response.connections
            )
            continue

        # Process each contact using outbox pattern
        for google_person, contact_data in serialized_contacts:
            try:
                # Create outbox event for contact sync
                outbox_event = OutboxEvent.create_contact_sync_event(
                    contact_data=contact_data,
                    integration_source="google_contacts",
                    external_id=google_person.resource_name,
                    sync_type="created",
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
                    error=str(e),
                )
                metrics["errors"] = metrics.get("errors", 0) + 1

        # Check for next page
        page_token = contacts_response.next_page_token
        if not page_token:
            break

    # Save sync token if available
    if contacts_response.next_sync_token:
        await _save_sync_token(
            session, google_account_email, contacts_response.next_sync_token
        )

    logger.info(
        "Full sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed,
    )

    return {"contacts_created": total_processed}


async def _perform_incremental_sync(
    session: AsyncSession,
    client: GoogleContactsAPIClient,
    google_account_email: str,
    metrics: dict[str, Any],
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
    result = await session.execute(
        stmt, {"user_id": SITE_USER_ID, "email": google_account_email}
    )
    sync_token = result.scalar()

    if not sync_token:
        logger.warning(
            "No sync token found for incremental sync, falling back to full sync",
            google_account_email=google_account_email,
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
            error=str(e),
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
                sync_type="updated",
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
                error=str(e),
            )
            metrics["errors"] = metrics.get("errors", 0) + 1

    # Save new sync token
    if contacts_response.next_sync_token:
        await _save_sync_token(
            session, google_account_email, contacts_response.next_sync_token
        )

    logger.info(
        "Incremental sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed,
    )

    return {"contacts_updated": total_processed}


async def _save_sync_token(
    session: AsyncSession, google_account_email: str, sync_token: str
) -> None:
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

    await session.execute(
        stmt,
        {
            "sync_token": sync_token,
            "updated_at": datetime.now(UTC),
            "user_id": SITE_USER_ID,
            "email": google_account_email,
        },
    )

    logger.info(
        "Saved sync token",
        google_account_email=google_account_email,
        sync_token_prefix=sync_token[:20] + "..."
        if len(sync_token) > 20
        else sync_token,
    )


async def sync_google_contacts(
    ctx: dict[str, Any], google_account_email: str, sync_type: str = "smart"
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
        worker_id=settings.worker_id,
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
                sync_type = await _determine_smart_sync_type(
                    session, google_account_email
                )
                logger.info(
                    "Smart sync determined sync type",
                    google_account_email=google_account_email,
                    determined_sync_type=sync_type,
                )

            # Perform sync based on type
            if sync_type == "full":
                result = await _perform_full_sync(
                    session, client, google_account_email, metrics
                )
            elif sync_type == "incremental":
                result = await _perform_incremental_sync(
                    session, client, google_account_email, metrics
                )
            else:
                raise ValueError(f"Unknown sync type: {sync_type}")

            metrics.update(result)
            metrics["completed_at"] = datetime.now(UTC).isoformat()

            # Create sync completion event
            completion_event = OutboxEvent.create_sync_completed_event(
                integration_source="google_contacts",
                google_account_email=google_account_email,
                metrics=metrics,
            )
            session.add(completion_event)

            # Commit all changes (contact events + completion event + sync token)
            await session.commit()

            logger.info(
                "Google Contacts sync task completed successfully",
                google_account_email=google_account_email,
                **metrics,
            )

            return {
                "status": "success",
                "google_account_email": google_account_email,
                **metrics,
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


async def push_local_contacts_to_google(
    ctx: dict[str, Any], google_account_email: str
) -> dict[str, Any]:
    """
    Push locally created/updated contacts to Google (two-way sync).

    This ARQ task finds contacts that were created or modified locally
    and pushes them to Google Contacts.

    Args:
        ctx: ARQ context dictionary
        google_account_email: Google account email to sync

    Returns:
        Task result dictionary with push status and metrics
    """
    logger.info(
        "Starting push local contacts to Google task",
        google_account_email=google_account_email,
        worker_id=settings.worker_id,
    )

    session_factory = ctx["session_factory"]

    # Initialize metrics
    metrics = {
        "pushed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0,
        "conflict_count": 0,
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

            # Find contacts that need to be pushed
            contacts_to_push = await find_contacts_to_push(
                session=session, integration_source="google_contacts"
            )

            if not contacts_to_push:
                logger.info(
                    "No local changes to push",
                    google_account_email=google_account_email,
                )
                metrics["completed_at"] = datetime.now(UTC).isoformat()
                return {
                    "status": "success",
                    "google_account_email": google_account_email,
                    **metrics,
                }

            # Push contacts to Google
            push_result = await push_contacts_to_google(
                session=session,
                client=client,
                contacts=contacts_to_push,
                google_account_email=google_account_email,
            )

            metrics.update(push_result)
            metrics["completed_at"] = datetime.now(UTC).isoformat()

            # Commit all sync metadata updates
            await session.commit()

            logger.info(
                "Push local contacts to Google task completed successfully",
                google_account_email=google_account_email,
                **metrics,
            )

            return {
                "status": "success",
                "google_account_email": google_account_email,
                **metrics,
            }

    except Exception as e:
        logger.error(
            "Push local contacts to Google task failed",
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
    functions = [sync_google_contacts, push_local_contacts_to_google]

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
