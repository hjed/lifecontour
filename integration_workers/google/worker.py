#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

import random
from datetime import UTC, datetime
from typing import Any

from arq import run_worker
from arq.connections import RedisSettings
from arq.cron import cron
from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared.database.engine import create_session_factory

# Import integration exceptions from core_shared
from core_shared.exceptions import JobCancelledException
from core_shared.integration_constants import (
    GOOGLE_ARQ_QUEUE_NAME as ARQ_QUEUE_NAME,
)

# Import shared observability modules
from core_shared.logging import (
    configure_logging,
    get_logger,
    set_job_id,
    set_worker_id,
)
from core_shared.metrics import MetricsCollector
from core_shared.models.contacts.serialization import serialize_contact
from core_shared.models.outbox import OutboxEvent
from core_shared.models.sync_metadata import SyncStatus
from core_shared.repositories import SyncJobRepository
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Import from the installed core_shared package
from api_models import ListConnectionsResponse

# Import worker-specific services
from google_auth_service import GoogleAuthService
from google_client import GoogleAPIClient
from transformer import GoogleContactTransformer


class WorkerSettings(BaseSettings):
    """Configuration for Google Contacts worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

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
    worker_id: str = "google-worker"
    log_level: str = "INFO"
    max_concurrent_jobs: int = 5

    # Periodic sync configuration
    enable_periodic_sync: bool = False
    sync_interval_hours: int = 6


# Global settings instance
settings = WorkerSettings()  # type: ignore[call-arg]

# Configure structured logging using shared module
configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)

# Initialize metrics collector for this worker
metrics_collector = MetricsCollector(worker_type="google")


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
    session: AsyncSession, integration_source: str = "google"
) -> list[dict[str, Any]]:
    """
    Find contacts that need to be pushed to Google.

    Identifies two types of contacts:
    1. Newly created contacts (no sync metadata entry)
    2. Updated contacts (updated_at > last_synced_at)

    Args:
        session: Database session
        integration_source: Integration source name (default: "google")

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


def _transform_names(contact: dict[str, Any]) -> list[dict[str, Any]]:
    """Transform contact names to Google Person format."""
    name_data: dict[str, Any] = {}
    if contact.get("first_name"):
        name_data["givenName"] = contact["first_name"]
    if contact.get("last_name"):
        name_data["familyName"] = contact["last_name"]
    if contact.get("middle_name"):
        name_data["middleName"] = contact["middle_name"]

    return [name_data] if name_data else []


def _transform_nicknames(contact: dict[str, Any]) -> list[dict[str, str]] | None:
    """Transform contact nickname to Google Person format."""
    if contact.get("nick_name"):
        return [{"value": contact["nick_name"]}]
    return None


def _normalize_contact_type(label: str | None) -> str:
    """
    Normalize contact method labels to Google's standard types.

    Google accepts custom types, but using standard types improves compatibility.
    Standard types: home, work, other, mobile, main

    Args:
        label: The label from our system (can be None or empty)

    Returns:
        Normalized type string (defaults to "other" if label is None/empty,
        or original label if no mapping exists)
    """
    if not label:
        return "other"

    normalized = label.strip().lower()
    label_mapping = {
        "work": "work",
        "office": "work",
        "business": "work",
        "home": "home",
        "personal": "home",
        "other": "other",
        "mobile": "mobile",
        "main": "main",
    }
    return label_mapping.get(normalized, label)  # Return original if no mapping


def _transform_email(method: dict[str, Any]) -> dict[str, Any]:
    """Transform a single email method to Google Person format."""
    email_data: dict[str, Any] = {"value": method["value"]}
    if method.get("label"):
        email_data["type"] = _normalize_contact_type(method["label"])
    if method.get("is_primary"):
        email_data["metadata"] = {"primary": True}
    return email_data


def _transform_phone(method: dict[str, Any]) -> dict[str, Any]:
    """Transform a single phone method to Google Person format."""
    phone_data: dict[str, Any] = {"value": method["value"]}
    if method.get("label"):
        phone_data["type"] = _normalize_contact_type(method["label"])
    if method.get("is_primary"):
        phone_data["metadata"] = {"primary": True}
    return phone_data


def _transform_contact_methods(
    methods: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Transform contact methods (emails and phones) to Google Person format."""
    email_addresses = []
    phone_numbers = []

    for method in methods:
        if method["method_type"] == "email":
            email_addresses.append(_transform_email(method))
        elif method["method_type"] == "phone":
            phone_numbers.append(_transform_phone(method))

    return email_addresses, phone_numbers


def _transform_address(addr: dict[str, Any]) -> dict[str, Any]:
    """Transform a single address to Google Person format."""
    addr_data: dict[str, Any] = {}

    # Build street address
    if addr.get("street_line_1"):
        addr_data["streetAddress"] = addr["street_line_1"]
    if addr.get("street_line_2"):
        if "streetAddress" in addr_data:
            addr_data["streetAddress"] += f"\n{addr['street_line_2']}"
        else:
            addr_data["streetAddress"] = addr["street_line_2"]

    # Add other address fields
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

    return addr_data


def _transform_addresses(addresses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transform addresses to Google Person format."""
    google_addresses = []
    for addr in addresses:
        addr_data = _transform_address(addr)
        if addr_data:
            google_addresses.append(addr_data)
    return google_addresses


def _transform_notes(notes: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    """Transform notes to Google Person biographies format."""
    if notes:
        combined_notes = "\n\n".join(note["content"] for note in notes)
        return [{"value": combined_notes, "contentType": "TEXT_PLAIN"}]
    return None


def _transform_organizations(contact: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Transform contact company and job_title to Google Person organizations format."""
    company = contact.get("company")
    job_title = contact.get("job_title")

    # Normalize whitespace - strip and convert empty strings to None
    if company:
        company = company.strip() if company.strip() else None
    if job_title:
        job_title = job_title.strip() if job_title.strip() else None

    # Only create organization if at least one field is present
    if not company and not job_title:
        return None

    organization_data: dict[str, Any] = {"current": True}

    if company:
        organization_data["name"] = company

    if job_title:
        organization_data["title"] = job_title

    return [organization_data]


def _transform_contact_to_google_person(contact: dict[str, Any]) -> dict[str, Any]:
    """
    Transform internal contact format to Google People API Person format.

    Args:
        contact: Contact dictionary with full data (including methods, addresses, notes)

    Returns:
        Dictionary in Google People API Person format
    """
    person_data: dict[str, Any] = {}

    # Transform names and nicknames
    names = _transform_names(contact)
    if names:
        person_data["names"] = names

    nicknames = _transform_nicknames(contact)
    if nicknames:
        person_data["nicknames"] = nicknames

    # Transform contact methods (emails and phones)
    methods = contact.get("methods", [])
    email_addresses, phone_numbers = _transform_contact_methods(methods)
    if email_addresses:
        person_data["emailAddresses"] = email_addresses
    if phone_numbers:
        person_data["phoneNumbers"] = phone_numbers

    # Transform addresses
    google_addresses = _transform_addresses(contact.get("addresses", []))
    if google_addresses:
        person_data["addresses"] = google_addresses

    # Transform notes to biographies
    biographies = _transform_notes(contact.get("notes", []))
    if biographies:
        person_data["biographies"] = biographies

    # Transform company and job_title to organizations
    organizations = _transform_organizations(contact)
    if organizations:
        person_data["organizations"] = organizations

    return person_data


async def _create_contact_in_google(
    session: AsyncSession,
    client: GoogleAPIClient,
    contact: dict[str, Any],
    person_data: dict[str, Any],
    google_account_email: str,
) -> dict[str, Any]:
    """Create a new contact in Google and update sync metadata."""
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
        integration_source="google",
    )

    logger.info(
        "Successfully created contact in Google",
        contact_id=contact["id"],
        resource_name=result["resourceName"],
    )

    return result


async def _update_contact_in_google(
    session: AsyncSession,
    client: GoogleAPIClient,
    contact: dict[str, Any],
    person_data: dict[str, Any],
    google_account_email: str,
) -> dict[str, Any]:
    """Update an existing contact in Google and update sync metadata."""
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
        integration_source="google",
    )

    logger.info(
        "Successfully updated contact in Google",
        contact_id=contact["id"],
        resource_name=result["resourceName"],
    )

    return result


def _handle_http_error(
    e: Exception, contact: dict[str, Any], metrics: dict[str, int]
) -> None:
    """Handle HTTP errors from Google API."""
    from googleapiclient.errors import HttpError

    if not isinstance(e, HttpError):
        raise e

    # Handle ETag conflicts (400 with failedPrecondition or 412 Precondition Failed)
    error_content = (
        e.content.decode() if isinstance(e.content, bytes) else str(e.content)
    )
    is_conflict = (
        e.resp.status == 412  # Standard HTTP precondition failed
        or (
            e.resp.status == 400 and "failed_precondition" in error_content.lower()
        )  # Google API specific
    )

    if is_conflict:
        logger.warning(
            "ETag conflict detected, skipping contact",
            contact_id=contact["id"],
            external_id=contact.get("external_id"),
            error=str(e),
            status_code=e.resp.status,
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


async def _push_single_contact(
    session: AsyncSession,
    client: GoogleAPIClient,
    contact: dict[str, Any],
    google_account_email: str,
    metrics: dict[str, int],
) -> None:
    """Push a single contact to Google."""
    from googleapiclient.errors import HttpError

    try:
        # Load full contact data (methods, addresses, notes)
        full_contact_data = await _load_full_contact(session, contact["id"])
        contact.update(full_contact_data)

        # Transform to Google Person format
        person_data = _transform_contact_to_google_person(contact)

        if contact["sync_action"] == "create":
            await _create_contact_in_google(
                session, client, contact, person_data, google_account_email
            )
            metrics["created_count"] += 1
            metrics["pushed_count"] += 1
        elif contact["sync_action"] == "update":
            await _update_contact_in_google(
                session, client, contact, person_data, google_account_email
            )
            metrics["updated_count"] += 1
            metrics["pushed_count"] += 1

    except HttpError as e:
        _handle_http_error(e, contact, metrics)
    except Exception as e:
        logger.error(
            "Unexpected error pushing contact to Google",
            contact_id=contact["id"],
            sync_action=contact["sync_action"],
            error=str(e),
        )
        metrics["error_count"] += 1


async def push_contacts_to_google(
    session: AsyncSession,
    client: GoogleAPIClient,
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
    metrics = {
        "pushed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0,
        "conflict_count": 0,
    }

    for contact in contacts:
        await _push_single_contact(
            session, client, contact, google_account_email, metrics
        )

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
    # Use empty string when no ETag is provided (version_hash column is NOT NULL)
    version_hash = etag or ""

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
    session: AsyncSession, google_account_email: str, user_id: str | int
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
        SELECT contacts_sync_token
        FROM user_google_integration
        WHERE user_id = :user_id AND google_account_email = :email
        AND contacts_sync_token IS NOT NULL
    """)
    result = await session.execute(
        stmt, {"user_id": str(user_id), "email": google_account_email}
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


def _process_contacts_batch(
    connections: list[Any],
    transformer: GoogleContactTransformer,
    google_account_email: str,
    metrics: dict[str, Any],
) -> list[tuple[Any, dict[str, Any]]]:
    """Process a batch of contacts, handling per-item failures gracefully."""

    serialized_contacts: list[tuple[Any, dict[str, Any]]] = []

    for person in connections:
        try:
            contact = transformer.transform_person(person)
            serialized = serialize_contact(contact)
            serialized_contacts.append((person, serialized))
        except Exception as e:
            logger.error(
                "Failed to transform/serialize contact in batch",
                google_account_email=google_account_email,
                resource_name=getattr(person, "resource_name", "unknown"),
                error=str(e),
            )
            metrics["errors"] = metrics.get("errors", 0) + 1

    return serialized_contacts


async def _perform_full_sync(
    session: AsyncSession,
    client: GoogleAPIClient,
    google_account_email: str,
    metrics: dict[str, Any],
    user_id: str | int,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Perform a full sync of Google Contacts.

    Args:
        session: Database session
        client: Google Contacts API client
        google_account_email: Google account email
        metrics: Metrics dictionary to update
        job_id: ARQ job ID for cancellation checks (optional)

    Returns:
        Updated metrics

    Raises:
        JobCancelledException: If job is cancelled by user
    """
    logger.info("Starting full sync", google_account_email=google_account_email)

    page_token = None
    total_processed = 0
    transformer = GoogleContactTransformer()

    while True:
        # Check if job has been cancelled
        if job_id and await _check_job_cancelled(session, job_id):
            raise JobCancelledException(job_id=job_id)

        # Fetch contacts from Google
        response = await client.list_connections(page_size=100, page_token=page_token)

        # Parse response
        contacts_response = ListConnectionsResponse(**response)

        if not contacts_response.connections:
            break

        # Transform and serialize contacts, handling per-item failures
        serialized_contacts = _process_contacts_batch(
            contacts_response.connections,
            transformer,
            google_account_email,
            metrics,
        )

        # Process each contact using outbox pattern
        for google_person, contact_data in serialized_contacts:
            try:
                # Create outbox event for contact sync
                outbox_event = OutboxEvent.create_contact_sync_event(
                    contact_data=contact_data,
                    integration_source="google",
                    external_id=google_person.resource_name,
                    sync_type="created",
                    etag=google_person.etag,
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
            session, google_account_email, contacts_response.next_sync_token, user_id
        )

    logger.info(
        "Full sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed,
    )

    return {"contacts_created": total_processed}


async def _perform_incremental_sync(
    session: AsyncSession,
    client: GoogleAPIClient,
    google_account_email: str,
    metrics: dict[str, Any],
    user_id: str | int,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Perform an incremental sync of Google Contacts using sync token.

    Args:
        session: Database session
        client: Google Contacts API client
        google_account_email: Google account email
        metrics: Metrics dictionary to update
        job_id: ARQ job ID for cancellation checks (optional)

    Returns:
        Updated metrics

    Raises:
        JobCancelledException: If job is cancelled by user
    """
    logger.info("Starting incremental sync", google_account_email=google_account_email)

    # Check if job has been cancelled
    if job_id and await _check_job_cancelled(session, job_id):
        raise JobCancelledException(job_id=job_id)

    # Get existing sync token
    stmt = text("""
        SELECT contacts_sync_token
        FROM user_google_integration
        WHERE user_id = :user_id AND google_account_email = :email
    """)
    result = await session.execute(
        stmt, {"user_id": str(user_id), "email": google_account_email}
    )
    sync_token = result.scalar()

    if not sync_token:
        logger.warning(
            "No sync token found for incremental sync, falling back to full sync",
            google_account_email=google_account_email,
        )
        return await _perform_full_sync(
            session, client, google_account_email, metrics, user_id, job_id
        )

    # Fetch changes since last sync
    response = await client.list_connections(sync_token=sync_token)
    contacts_response = ListConnectionsResponse(**response)

    total_processed = 0

    # Transform and serialize contacts, handling per-item failures
    transformer = GoogleContactTransformer()
    serialized_contacts = _process_contacts_batch(
        contacts_response.connections,
        transformer,
        google_account_email,
        metrics,
    )

    # Process changed contacts using outbox pattern
    for google_person, contact_data in serialized_contacts:
        try:
            # Create outbox event for contact sync
            outbox_event = OutboxEvent.create_contact_sync_event(
                contact_data=contact_data,
                integration_source="google",
                external_id=google_person.resource_name,
                sync_type="updated",
                etag=google_person.etag,
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
            session, google_account_email, contacts_response.next_sync_token, user_id
        )

    logger.info(
        "Incremental sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed,
    )

    return {"contacts_updated": total_processed}


async def _save_sync_token(
    session: AsyncSession,
    google_account_email: str,
    sync_token: str,
    user_id: str | int,
) -> None:
    """
    Save sync token for future incremental syncs.

    Args:
        session: Database session
        google_account_email: Google account email
        sync_token: Sync token from Google API
    """
    stmt = text("""
        INSERT INTO user_google_integration
            (user_id, google_account_email, contacts_sync_token, created_at, updated_at)
        VALUES
            (:user_id, :email, :sync_token, :updated_at, :updated_at)
        ON CONFLICT (user_id, google_account_email)
        DO UPDATE SET
            contacts_sync_token = EXCLUDED.contacts_sync_token,
            updated_at = EXCLUDED.updated_at
    """)

    await session.execute(
        stmt,
        {
            "sync_token": sync_token,
            "updated_at": datetime.now(UTC),
            "user_id": str(user_id),
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


async def _update_sync_job_status(
    session: AsyncSession,
    job_id: str,
    status: str,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error_message: str | None = None,
    contacts_processed: int | None = None,
    contacts_created: int | None = None,
    contacts_updated: int | None = None,
    contacts_deleted: int | None = None,
    progress: int | None = None,
) -> None:
    """
    Update sync job status in the database using the repository.

    Args:
        session: Database session
        job_id: ARQ job ID
        status: New status
        started_at: When the job started (optional)
        completed_at: When the job completed (optional)
        error_message: Error message if failed (optional)

        contacts_processed: Number of contacts processed (optional)
        contacts_created: Number of contacts created (optional)
        contacts_updated: Number of contacts updated (optional)
        contacts_deleted: Number of contacts deleted (optional)
        progress: Progress percentage 0-100 (optional)
    """
    # Get connection from session
    conn = await session.connection()
    repo = SyncJobRepository(conn)

    # Update job status using repository
    result = await repo.update_status(
        job_id=job_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        error_message=error_message,
        contacts_processed=contacts_processed,
        contacts_created=contacts_created,
        contacts_updated=contacts_updated,
        contacts_deleted=contacts_deleted,
        progress=progress,
    )

    # Log warning if no row was updated
    if result is None:
        logger.warning(
            "Failed to update sync job status - job not found",
            job_id=job_id,
            status=status,
        )


async def _check_job_cancelled(session: AsyncSession, job_id: str) -> bool:
    """
    Check if a job has been cancelled.

    Args:
        session: Database session
        job_id: ARQ job ID to check

    Returns:
        True if job is cancelled, False otherwise
    """
    conn = await session.connection()
    repo = SyncJobRepository(conn)

    # Get job from database
    job = await repo.get_by_job_id(job_id)

    if job and job.status == "cancelled":
        logger.info("Job has been cancelled", job_id=job_id)
        return True

    return False


async def periodic_sync_all_accounts(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Periodic sync wrapper that syncs all active Google accounts.

    This function is called by ARQ cron jobs and enqueues individual sync tasks
    for each active Google integration. It only takes ctx as a parameter (ARQ requirement).

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory

    Returns:
        Dictionary with sync summary (accounts_found, jobs_enqueued, errors)
    """
    logger.info("Starting periodic sync for all Google accounts")

    # Get session factory from context
    session_factory = ctx["session_factory"]

    accounts_found = 0
    jobs_enqueued = 0
    errors = []

    try:
        # Create database session
        async with session_factory() as session:
            # Query all Google integrations (all accounts in table are considered active)
            stmt = text("""
                SELECT user_id, google_account_email
                FROM user_google_auth
                ORDER BY user_id
            """)
            result = await session.execute(stmt)
            accounts = result.fetchall()

            accounts_found = len(accounts)
            logger.info(
                "Found active Google accounts for periodic sync",
                accounts_count=accounts_found,
            )

            # Enqueue sync job for each account
            for row in accounts:
                user_id = row[0]
                google_account_email = row[1]

                try:
                    # Enqueue individual sync job using ARQ pool from context
                    job = await ctx["redis"].enqueue_job(
                        "sync_google",
                        google_account_email,
                        user_id,
                        "smart",  # Use smart sync for periodic syncs
                        _job_timeout=600,  # 10 minutes
                        _queue_name=ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic sync job",
                            job_id=job.job_id,
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue job for {google_account_email}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic sync job",
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )

                except Exception as e:
                    error_msg = (
                        f"Error enqueueing job for {google_account_email}: {str(e)}"
                    )
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic sync job",
                        google_account_email=google_account_email,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        logger.info(
            "Periodic sync scheduling complete",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            errors_count=len(errors),
        )

        return {
            "status": "success",
            "accounts_found": accounts_found,
            "jobs_enqueued": jobs_enqueued,
            "errors": errors,
        }

    except Exception as e:
        logger.error(
            "Periodic sync scheduling failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def sync_google(
    ctx: dict[str, Any],
    google_account_email: str,
    user_id: str | int,
    sync_type: str = "smart",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Sync Google Contacts for a specific Google account.

    This is the main ARQ task that handles Google Contacts synchronization.
    It implements the smart sync strategy and idempotent operations.

    Args:
        ctx: ARQ context dictionary
        google_account_email: Google account email to sync
        user_id: User ID who initiated the sync
        sync_type: Type of sync - "full", "incremental", or "smart" (default)

    Returns:
        Task result dictionary with sync status and metrics
    """
    # Get job_id from ARQ context
    job_id = ctx.get("job_id", "unknown")

    # Set context for logging
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    logger.info(
        "Starting Google Contacts sync task",
        job_id=job_id,
        google_account_email=google_account_email,
        sync_type=sync_type,
        worker_id=settings.worker_id,
    )

    session_factory = ctx["session_factory"]

    # Initialize metrics
    metrics: dict[str, Any] = {
        "contacts_processed": 0,
        "contacts_created": 0,
        "contacts_updated": 0,
        "contacts_deleted": 0,
        "sync_type_used": sync_type,
        "worker_id": settings.worker_id,
        "started_at": datetime.now(UTC).isoformat(),
    }

    started_at = datetime.now(UTC)

    try:
        # Use session-per-task pattern
        async with session_factory() as session:
            # Update job status to running
            await _update_sync_job_status(
                session=session,
                job_id=job_id,
                status="running",
                started_at=started_at,
                progress=0,
            )
            await session.commit()

            # Create services
            auth_service = GoogleAuthService(
                session=session,
                encryption_key=settings.encryption_key.get_secret_value(),
                google_client_id=settings.google_client_id,
                google_client_secret=settings.google_client_secret.get_secret_value(),
            )

            client = GoogleAPIClient(
                auth_service=auth_service,
                google_account_email=google_account_email,
                google_client_id=settings.google_client_id,
                google_client_secret=settings.google_client_secret.get_secret_value(),
                user_id=user_id,
            )

            # Determine sync strategy
            if sync_type == "smart":
                sync_type = await _determine_smart_sync_type(
                    session, google_account_email, user_id
                )
                logger.info(
                    "Smart sync determined sync type",
                    google_account_email=google_account_email,
                    determined_sync_type=sync_type,
                )

            # Perform sync based on type
            if sync_type == "full":
                result = await _perform_full_sync(
                    session, client, google_account_email, metrics, user_id, job_id
                )
            elif sync_type == "incremental":
                result = await _perform_incremental_sync(
                    session, client, google_account_email, metrics, user_id, job_id
                )
            else:
                raise ValueError(f"Unknown sync type: {sync_type}")

            metrics.update(result)
            completed_at = datetime.now(UTC)
            metrics["completed_at"] = completed_at.isoformat()

            # Calculate job duration
            duration = (completed_at - started_at).total_seconds()

            # Update job status to completed
            await _update_sync_job_status(
                session=session,
                job_id=job_id,
                status="completed",
                completed_at=completed_at,
                contacts_processed=metrics.get("contacts_processed", 0),
                contacts_created=metrics.get("contacts_created", 0),
                contacts_updated=metrics.get("contacts_updated", 0),
                contacts_deleted=metrics.get("contacts_deleted", 0),
                progress=100,
            )

            # Create sync completion event
            completion_event = OutboxEvent.create_sync_completed_event(
                integration_source="google",
                google_account_email=google_account_email,
                metrics=metrics,
            )
            session.add(completion_event)

            # Commit all changes (contact events + completion event + sync token + job status)
            await session.commit()

            # Record metrics
            metrics_collector.record_job_duration(
                job_type="sync", status="success", duration=duration
            )
            metrics_collector.increment_job_total(job_type="sync", status="success")
            metrics_collector.increment_items_processed(
                sync_type=metrics.get("sync_type_used", "unknown"),
                action="created",
                count=metrics.get("contacts_created", 0),
            )
            metrics_collector.increment_items_processed(
                sync_type=metrics.get("sync_type_used", "unknown"),
                action="updated",
                count=metrics.get("contacts_updated", 0),
            )
            metrics_collector.increment_items_processed(
                sync_type=metrics.get("sync_type_used", "unknown"),
                action="deleted",
                count=metrics.get("contacts_deleted", 0),
            )

            logger.info(
                "Google Contacts sync task completed successfully",
                job_id=job_id,
                google_account_email=google_account_email,
                duration_seconds=duration,
                **metrics,
            )

            return {
                "status": "success",
                "google_account_email": google_account_email,
                **metrics,
            }

    except JobCancelledException:
        # Calculate duration for cancellation case
        duration = (datetime.now(UTC) - started_at).total_seconds()

        logger.info(
            "Google Contacts sync task cancelled",
            job_id=job_id,
            google_account_email=google_account_email,
            duration_seconds=duration,
        )

        # Record cancellation metrics
        metrics_collector.record_job_duration(
            job_type="sync", status="cancelled", duration=duration
        )
        metrics_collector.increment_job_total(job_type="sync", status="cancelled")

        # Job status is already set to cancelled in the database
        # No need to update it again
        return {
            "status": "cancelled",
            "google_account_email": google_account_email,
            "message": "Job cancelled by user",
            "worker_id": settings.worker_id,
            "cancelled_at": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        # Calculate duration for error case
        duration = (datetime.now(UTC) - started_at).total_seconds()

        logger.error(
            "Google Contacts sync task failed",
            job_id=job_id,
            google_account_email=google_account_email,
            error=str(e),
            error_type=type(e).__name__,
            duration_seconds=duration,
        )

        # Record error metrics
        metrics_collector.record_job_duration(
            job_type="sync", status="error", duration=duration
        )
        metrics_collector.increment_job_total(job_type="sync", status="error")
        metrics_collector.increment_sync_errors(
            sync_type=sync_type, error_type=type(e).__name__
        )

        # Update job status to failed
        try:
            async with session_factory() as session:
                await _update_sync_job_status(
                    session=session,
                    job_id=job_id,
                    status="failed",
                    completed_at=datetime.now(UTC),
                    error_message=str(e),
                )
                await session.commit()
        except Exception as update_error:
            logger.error(
                "Failed to update job status to failed",
                job_id=job_id,
                error=str(update_error),
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
    ctx: dict[str, Any], google_account_email: str, user_id: str | int = 1
) -> dict[str, Any]:
    """
    Push locally created/updated contacts to Google (two-way sync).

    This ARQ task finds contacts that were created or modified locally
    and pushes them to Google Contacts.

    Args:
        ctx: ARQ context dictionary
        google_account_email: Google account email to sync
        user_id: User identifier

    Returns:
        Task result dictionary with push status and metrics
    """
    # Get job_id from ARQ context
    job_id = ctx.get("job_id", "unknown")

    # Set context for logging
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    logger.info(
        "Starting push local contacts to Google task",
        job_id=job_id,
        google_account_email=google_account_email,
        worker_id=settings.worker_id,
    )

    session_factory = ctx["session_factory"]

    # Initialize metrics
    metrics: dict[str, Any] = {
        "pushed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "error_count": 0,
        "conflict_count": 0,
        "worker_id": settings.worker_id,
        "started_at": datetime.now(UTC).isoformat(),
    }

    started_at = datetime.now(UTC)

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

            client = GoogleAPIClient(
                auth_service=auth_service,
                google_account_email=google_account_email,
                google_client_id=settings.google_client_id,
                google_client_secret=settings.google_client_secret.get_secret_value(),
                user_id=user_id,
            )

            # Find contacts that need to be pushed
            contacts_to_push = await find_contacts_to_push(
                session=session, integration_source="google"
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

            # Calculate duration
            duration = (datetime.now(UTC) - started_at).total_seconds()

            # Commit all sync metadata updates
            await session.commit()

            # Record metrics
            metrics_collector.record_job_duration(
                job_type="push", status="success", duration=duration
            )
            metrics_collector.increment_job_total(job_type="push", status="success")
            metrics_collector.increment_items_processed(
                sync_type="push",
                action="created",
                count=metrics.get("created_count", 0),
            )
            metrics_collector.increment_items_processed(
                sync_type="push",
                action="updated",
                count=metrics.get("updated_count", 0),
            )
            if metrics.get("conflict_count", 0) > 0:
                metrics_collector.increment_sync_conflicts(sync_type="push")

            logger.info(
                "Push local contacts to Google task completed successfully",
                job_id=job_id,
                google_account_email=google_account_email,
                duration_seconds=duration,
                **metrics,
            )

            return {
                "status": "success",
                "google_account_email": google_account_email,
                **metrics,
            }

    except Exception as e:
        # Calculate duration for error case
        duration = (datetime.now(UTC) - started_at).total_seconds()

        logger.error(
            "Push local contacts to Google task failed",
            job_id=job_id,
            google_account_email=google_account_email,
            error=str(e),
            error_type=type(e).__name__,
            duration_seconds=duration,
        )

        # Record error metrics
        metrics_collector.record_job_duration(
            job_type="push", status="error", duration=duration
        )
        metrics_collector.increment_job_total(job_type="push", status="error")
        metrics_collector.increment_sync_errors(
            sync_type="push", error_type=type(e).__name__
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


def retry_delay_func(retry_count: int) -> float:
    """
    Calculate retry delay with exponential backoff and jitter.

    Implements exponential backoff strategy:
    - Retry 0 (1st retry): ~60s (48-72s with jitter)
    - Retry 1 (2nd retry): ~120s (96-144s with jitter)
    - Retry 2 (3rd retry): ~240s (192-288s with jitter)
    - Retry 3 (4th retry): ~480s (384-576s with jitter)
    - Retry 4+ (5th+ retry): capped at 900s (720-900s with jitter)

    Note: Jitter is intentionally random (±20%) to prevent thundering herd problems
    in production. Unit tests verify correct behavior by testing many samples and
    checking that average delays match expected values.

    Args:
        retry_count: Number of retries already attempted (0-based)

    Returns:
        Delay in seconds before next retry
    """
    # Base delay: 60 seconds
    base_delay = 60

    # Exponential backoff: 60 * (2 ^ retry_count)
    delay = base_delay * (2**retry_count)

    # Apply jitter: ±20% to prevent thundering herd
    jitter = random.uniform(0.8, 1.2)
    delay_with_jitter = delay * jitter

    # Cap at 15 minutes (900 seconds)
    return float(min(delay_with_jitter, 900.0))


# ARQ Worker Settings
class GoogleWorkerSettings(WorkerSettingsBase):
    """ARQ worker configuration."""

    # Task functions
    functions = [
        sync_google,
        push_local_contacts_to_google,
        periodic_sync_all_accounts,  # Wrapper for periodic cron syncs
    ]

    # Worker lifecycle
    on_startup: StartupShutdown = startup
    on_shutdown: StartupShutdown = shutdown

    # Redis settings
    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Worker configuration
    max_jobs = settings.max_concurrent_jobs
    job_timeout = 600  # 10 minutes
    keep_result = 3600  # Keep results for 1 hour

    # Retry configuration with exponential backoff
    max_tries = 5
    retry_delay = retry_delay_func  # Use function for exponential backoff with jitter

    # Queue name
    queue_name = ARQ_QUEUE_NAME

    # Periodic sync configuration (cron jobs)
    # Only configure cron_jobs if periodic sync is enabled
    cron_jobs = []
    if settings.enable_periodic_sync:
        # Generate cron schedule based on sync_interval_hours
        # For example: sync_interval_hours=6 -> hours={0, 6, 12, 18}
        sync_hours = set(range(0, 24, settings.sync_interval_hours))

        # Schedule periodic_sync_all_accounts to run at configured intervals
        # This function queries all active Google integrations and enqueues
        # individual sync jobs for each account
        cron_jobs = [
            cron(
                periodic_sync_all_accounts,
                hour=sync_hours,
                minute=0,  # Run at the top of the hour
                unique=True,  # Only run once even with multiple workers
            )
        ]

        logger.info(
            "Periodic sync enabled",
            sync_interval_hours=settings.sync_interval_hours,
            sync_hours=list(sync_hours),
        )


if __name__ == "__main__":
    # Run the worker
    logger.info("Starting Google Contacts ARQ worker", worker_id=settings.worker_id)
    run_worker(GoogleWorkerSettings)
