#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

from datetime import UTC, datetime, timedelta
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
from group_mapping import _build_contact_group_mapping
from group_translator import GoogleGroupNameTranslator
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

    # Reserved google groups to ignore (by default just myContacts)
    google_reserved_groups: list[str] = ["myContacts"]

    # Webhook configuration
    webhook_base_url: str = ""  # Public HTTPS URL for webhook callbacks


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


async def startup(ctx: dict[str, Any]) -> None:  # NOSONAR
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

    # Load contact tags
    tags = await _load_tag_names_for_contact(session, contact_id)

    # Load important dates
    dates_stmt = text("""
        SELECT id, date_type, precision, year, month, day, custom_date_type_id
        FROM contact_important_dates
        WHERE contact_id = :contact_id
        ORDER BY id ASC
    """)
    dates_result = await session.execute(dates_stmt, {"contact_id": contact_id})
    dates_rows = dates_result.fetchall()
    important_dates = [
        {
            "id": row.id,
            "date_type": row.date_type,
            "precision": row.precision,
            "year": row.year,
            "month": row.month,
            "day": row.day,
            "custom_date_type_id": row.custom_date_type_id,
        }
        for row in dates_rows
    ]

    return {
        "methods": methods,
        "addresses": addresses,
        "notes": notes,
        "tags": tags,
        "important_dates": important_dates,
    }


async def _load_tag_names_for_contact(
    session: AsyncSession, contact_id: int
) -> list[str]:
    """
    Load tag names assigned to a contact, using hierarchical path names.

    For tags with parent_id, builds path-style names by walking up the
    parent chain (e.g., "Family/Extended"). Root tags keep flat names.

    Args:
        session: Database session
        contact_id: Contact ID

    Returns:
        List of tag name strings (with hierarchy paths for child tags)
    """
    tags_stmt = text("""
        WITH RECURSIVE tag_paths AS (
            -- Base case: tags assigned to this contact
            SELECT t.id, t.parent_id, t.name::TEXT AS path, t.id AS original_tag_id
            FROM tags t
            INNER JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE ct.contact_id = :contact_id

            UNION ALL

            -- Recursive case: prepend parent name
            SELECT t.id, t.parent_id, t.name || '/' || tp.path AS path, tp.original_tag_id
            FROM tags t
            INNER JOIN tag_paths tp ON tp.parent_id = t.id
        )
        SELECT path AS name
        FROM tag_paths
        WHERE parent_id IS NULL
        ORDER BY path ASC
    """)
    tags_result = await session.execute(tags_stmt, {"contact_id": contact_id})
    return [row.name for row in tags_result.fetchall()]


async def _load_tag_names_for_contacts_batch(
    session: AsyncSession, contact_ids: list[int]
) -> dict[int, list[str]]:
    """
    Load tag names for multiple contacts in a single query.

    Uses recursive CTE to build path-style names for hierarchical tags.
    More efficient than calling _load_tag_names_for_contact per contact
    when processing batches.

    Args:
        session: Database session
        contact_ids: List of contact IDs

    Returns:
        Mapping of contact_id → sorted list of tag name strings (with hierarchy paths).
        Contacts with no tags will have an empty list.
    """
    if not contact_ids:
        return {}

    tags_stmt = text("""
        WITH RECURSIVE tag_paths AS (
            -- Base case: tags assigned to the contacts
            SELECT t.id, t.parent_id, t.name::TEXT AS path, ct.contact_id
            FROM tags t
            INNER JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE ct.contact_id = ANY(:contact_ids)

            UNION ALL

            -- Recursive case: prepend parent name
            SELECT t.id, t.parent_id, t.name || '/' || tp.path AS path, tp.contact_id
            FROM tags t
            INNER JOIN tag_paths tp ON tp.parent_id = t.id
        )
        SELECT contact_id, path AS name
        FROM tag_paths
        WHERE parent_id IS NULL
        ORDER BY contact_id, path ASC
    """)
    tags_result = await session.execute(tags_stmt, {"contact_ids": contact_ids})

    result: dict[int, list[str]] = {cid: [] for cid in contact_ids}
    for row in tags_result.fetchall():
        result[row.contact_id].append(row.name)
    return result


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

    # Transform tags to Google group memberships
    tag_names = contact.get("tags", [])
    if "group_name_to_resource" in contact:
        group_name_to_resource = contact["group_name_to_resource"]
        # Always include memberships when tag push is active (group mapping
        # provided), even if empty, so that removed local tags clear existing
        # Google group memberships via the updatePersonFields mask.
        memberships = (
            _transform_tags_to_memberships(tag_names, group_name_to_resource)
            if tag_names and group_name_to_resource
            else []
        )
        person_data["memberships"] = memberships

    # Transform important dates to Google birthdays and events
    # Always include birthdays/events when important_dates is present on the
    # contact, even if the transformed supported lists are empty, so removals
    # propagate through the updatePersonFields mask and clear stale Google data.
    if "important_dates" in contact:
        important_dates = contact.get("important_dates") or []
        birthdays, events = _transform_important_dates_to_google(important_dates)
        person_data["birthdays"] = birthdays
        person_data["events"] = events

    return person_data


def _transform_tags_to_memberships(
    tag_names: list[str],
    group_name_to_resource: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Transform local tag names to Google People API memberships format.

    Args:
        tag_names: List of local tag names
        group_name_to_resource: Mapping of tag name to Google group resource name

    Returns:
        List of membership dictionaries in Google format
    """
    memberships = []
    for tag_name in tag_names:
        resource_name = group_name_to_resource.get(tag_name)
        if resource_name:
            memberships.append(
                {"contactGroupMembership": {"contactGroupResourceName": resource_name}}
            )
    return memberships


def _build_reverse_group_mapping(
    forward_mapping: dict[str, str],
) -> dict[str, str]:
    """
    Build a name→resource_name mapping from a resource_name→name mapping.

    The forward mapping (used for pull) maps Google group resource names to
    display names. The reverse mapping (used for push) maps display names
    back to resource names.

    Note: Google allows duplicate group display names. When duplicates exist,
    the last resource name seen wins. A warning is logged for visibility.

    Args:
        forward_mapping: resource_name → display_name mapping

    Returns:
        display_name → resource_name mapping
    """
    reverse: dict[str, str] = {}
    for resource_name, name in forward_mapping.items():
        if name in reverse:
            logger.warning(
                "Duplicate Google Contact Group name detected, last resource wins",
                group_name=name,
                previous_resource=reverse[name],
                new_resource=resource_name,
            )
        reverse[name] = resource_name
    return reverse


def _transform_important_dates_to_google(
    dates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Transform internal important date dicts to Google People API format.

    Only Google-supported date types are included:
    - BIRTHDAY → birthdays field
    - MARRIAGE_ANNIVERSARY → events field with type="anniversary"

    Local-only types (WORK_ANNIVERSARY, FIRST_MET, CUSTOM) are silently
    skipped.

    Internal precision is mapped back to Google's zero-means-unset convention:
    - FULL → {year, month, day}
    - DAY_MONTH → {year: 0, month, day}
    - YEAR → {year, month: 0, day: 0}

    Args:
        dates: List of important date dicts with date_type, precision, year, month, day

    Returns:
        Tuple of (birthdays_list, events_list) in Google Person format
    """
    birthdays: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for date in dates:
        date_type = date.get("date_type")
        precision = date.get("precision")
        google_date = _precision_to_google_date(
            precision=precision,
            year=date.get("year"),
            month=date.get("month"),
            day=date.get("day"),
        )

        if date_type == "birthday":
            birthdays.append({"date": google_date})
        elif date_type == "marriage_anniversary":
            events.append({"date": google_date, "type": "anniversary"})
        # All other types are local-only — silently skip

    return birthdays, events


def _precision_to_google_date(
    precision: str | None,
    year: int | None,
    month: int | None,
    day: int | None,
) -> dict[str, int]:
    """Map internal date precision to Google Date with zero-means-unset."""
    if precision == "full":
        return {"year": year or 0, "month": month or 0, "day": day or 0}
    elif precision == "day_month":
        return {"year": 0, "month": month or 0, "day": day or 0}
    elif precision == "year":
        return {"year": year or 0, "month": 0, "day": 0}
    else:
        return {"year": year or 0, "month": month or 0, "day": day or 0}


async def _ensure_google_groups_exist(
    client: GoogleAPIClient,
    tag_names: list[str],
    existing_groups: dict[str, str],
) -> dict[str, str]:
    """
    Ensure Google Contact Groups exist for all local tag names.

    Creates missing groups via the Google API. Returns a complete mapping
    of tag name → group resource name.

    Args:
        client: Google Contacts API client
        tag_names: List of local tag names that need groups
        existing_groups: Known tag name → group resource name mapping

    Returns:
        Updated tag name → group resource name mapping
    """
    updated_mapping = dict(existing_groups)

    for tag_name in tag_names:
        if tag_name in updated_mapping:
            continue

        try:
            result = await client.create_contact_group(tag_name)
            resource_name = result.get("resourceName")
            if resource_name:
                updated_mapping[tag_name] = resource_name
                logger.info(
                    "Created Google Contact Group for local tag",
                    tag_name=tag_name,
                    resource_name=resource_name,
                )
        except Exception as e:
            logger.warning(
                "Failed to create Google Contact Group for tag",
                tag_name=tag_name,
                error=str(e),
            )
            # Continue without this group — tag won't be synced this cycle

    return updated_mapping


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
    group_name_to_resource: dict[str, str] | None = None,
) -> None:
    """Push a single contact to Google."""
    from googleapiclient.errors import HttpError

    try:
        # Load full contact data (methods, addresses, notes, tags)
        full_contact_data = await _load_full_contact(session, contact["id"])
        contact.update(full_contact_data)

        # Add group mapping for tag→membership transformation.
        # Use `is not None` so an empty dict still activates membership
        # clearing (sends empty memberships list to Google).
        if group_name_to_resource is not None:
            contact["group_name_to_resource"] = group_name_to_resource

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
    group_name_to_resource: dict[str, str] | None = None,
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
            session,
            client,
            contact,
            google_account_email,
            metrics,
            group_name_to_resource=group_name_to_resource,
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


async def _create_transformer(
    client: GoogleAPIClient,
) -> GoogleContactTransformer:
    """
    Create a GoogleContactTransformer with a populated name translator.

    Fetches contact groups to build the translation mapping.
    """
    group_mapping = await _build_contact_group_mapping(client)

    translator = GoogleGroupNameTranslator(
        reserved_group_ids=settings.google_reserved_groups, group_mapping=group_mapping
    )

    return GoogleContactTransformer(translator=translator)


async def _find_existing_external_ids(
    session: AsyncSession,
    external_ids: list[str],
    integration_source: str,
) -> set[str]:
    """
    Find which external IDs already have sync metadata.

    Args:
        session: Database session
        external_ids: List of external IDs to check
        integration_source: Integration source (e.g., 'google')

    Returns:
        Set of external IDs that already have sync metadata
    """
    if not external_ids:
        return set()

    # Use ANY() with array parameter for efficient batch lookup
    stmt = text("""
        SELECT external_id
        FROM sync_metadata
        WHERE integration_source = :integration_source
          AND external_id = ANY(:external_ids)
    """)

    result = await session.execute(
        stmt,
        {
            "integration_source": integration_source,
            "external_ids": external_ids,
        },
    )
    return {row[0] for row in result.fetchall()}


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
    created_count = 0
    updated_count = 0
    transformer = await _create_transformer(client)

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

        # Determine which contacts already exist via sync metadata
        batch_external_ids = [
            google_person.resource_name for google_person, _ in serialized_contacts
        ]
        existing_external_ids = await _find_existing_external_ids(
            session, batch_external_ids, "google"
        )

        # Process each contact using outbox pattern
        for google_person, contact_data in serialized_contacts:
            try:
                # Use 'updated' for contacts that already have sync metadata,
                # 'created' for new contacts
                sync_type = (
                    "updated"
                    if google_person.resource_name in existing_external_ids
                    else "created"
                )

                # Create outbox event for contact sync
                outbox_event = OutboxEvent.create_contact_sync_event(
                    contact_data=contact_data,
                    integration_source="google",
                    external_id=google_person.resource_name,
                    sync_type=sync_type,
                    etag=google_person.etag,
                )

                # Add to session (will be committed with transaction)
                session.add(outbox_event)

                if sync_type == "created":
                    created_count += 1
                else:
                    updated_count += 1
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

    total_processed = created_count + updated_count
    logger.info(
        "Full sync completed",
        google_account_email=google_account_email,
        total_processed=total_processed,
        created_count=created_count,
        updated_count=updated_count,
    )

    return {"contacts_created": created_count, "contacts_updated": updated_count}


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
    transformer = await _create_transformer(client)
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

            # Enqueue sync jobs for each account (both contacts and calendar)
            for row in accounts:
                user_id = row[0]
                google_account_email = row[1]

                # Enqueue contacts sync
                try:
                    job = await ctx["redis"].enqueue_job(
                        "sync_google_contacts",
                        google_account_email,
                        user_id,
                        "smart",  # Use smart sync for periodic syncs
                        _job_timeout=600,  # 10 minutes
                        _queue_name=ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic contacts sync job",
                            job_id=job.job_id,
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue contacts sync for {google_account_email}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic contacts sync job",
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )

                except Exception as e:
                    error_msg = f"Error enqueueing contacts sync for {google_account_email}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic contacts sync job",
                        google_account_email=google_account_email,
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

                # Enqueue calendar events sync
                try:
                    cal_job = await ctx["redis"].enqueue_job(
                        "sync_calendar_events",
                        google_account_email,
                        user_id,
                        "smart",
                        _job_timeout=600,
                        _queue_name=ARQ_QUEUE_NAME,
                    )

                    if cal_job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic calendar sync job",
                            job_id=cal_job.job_id,
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue calendar sync for {google_account_email}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic calendar sync job",
                            google_account_email=google_account_email,
                            user_id=user_id,
                        )

                except Exception as e:
                    error_msg = f"Error enqueueing calendar sync for {google_account_email}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic calendar sync job",
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


async def sync_google_contacts(
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


async def _process_journal_deleted_event(
    session_factory: Any, event_data: dict[str, Any], journal_id: int
) -> dict[str, Any]:
    user_id = event_data.get("user_id")
    if not user_id:
        logger.error("JournalDeleted event missing user_id", journal_id=journal_id)
        return {"status": "error", "reason": "Missing user_id for deletion"}

    external_identifiers = event_data.get("external_identifiers", {})
    google_event_ids_raw = external_identifiers.get("google")

    if not google_event_ids_raw:
        logger.debug("Ignoring JournalDeleted: No Google event ID found in payload")
        return {"status": "ignored", "reason": "no_external_id_for_provider"}

    google_events = (
        google_event_ids_raw
        if isinstance(google_event_ids_raw, list)
        else [google_event_ids_raw]
    )

    async with session_factory() as session:
        auth_stmt = text("""
            SELECT google_account_email
            FROM user_google_integration
            WHERE user_id = :user_id
            LIMIT 1
        """)
        auth_result = await session.execute(auth_stmt, {"user_id": str(user_id)})
        auth_row = auth_result.fetchone()

        if not auth_row:
            logger.warning("No Google integration found for user", user_id=user_id)
            return {"status": "error", "reason": "auth_not_found"}

        google_account_email = auth_row.google_account_email
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

        deleted_ids = []
        errors = []
        from googleapiclient.errors import HttpError

        for google_event in google_events:
            try:
                if isinstance(google_event, str):
                    google_event_id = google_event
                    calendar_id = event_data.get("google_calendar_id") or "primary"
                else:
                    google_event_id = google_event.get("external_event_id")
                    calendar_id = (
                        google_event.get("google_calendar_id")
                        or event_data.get("google_calendar_id")
                        or "primary"
                    )

                if not google_event_id:
                    continue

                await client.delete_event(google_event_id, calendar_id)
                logger.info(
                    "Deleted journal event from Google Calendar",
                    journal_id=journal_id,
                )
                deleted_ids.append(google_event_id)
            except HttpError as e:
                # 404 (Not Found) or 410 (Gone) mean it's already deleted
                if e.resp.status in (404, 410):
                    logger.info(
                        "Event already deleted or not found on Google Calendar",
                        google_event_id=google_event_id,
                        journal_id=journal_id,
                    )
                    deleted_ids.append(google_event_id)
                else:
                    logger.error(
                        "HTTP error deleting journal event from Google Calendar",
                        error=str(e),
                        journal_id=journal_id,
                    )
                    errors.append(str(e))
            except Exception as e:
                logger.error(
                    "Failed to delete journal event from Google Calendar",
                    error=str(e),
                    journal_id=journal_id,
                )
                errors.append(str(e))

        if errors:
            raise RuntimeError("Failed to delete some events: " + ", ".join(errors))

        return {
            "status": "success",
            "action": "delete",
            "external_event_ids": deleted_ids,
        }


async def _process_journal_upsert_event(
    session_factory: Any,
    event_type: str,
    event_data: dict[str, Any],
    journal_id: int,
    started_at: datetime,
) -> dict[str, Any]:
    async with session_factory() as session:
        stmt = text("""
            SELECT
                j.id as journal_id,
                j.title,
                j.content,
                j.event_date_range_start,
                j.event_date_range_end,
                j.user_id,
                jci.is_all_day,
                jci.location,
                jci.calendar_id,
                c.is_synced_to_google,
                c.google_calendar_id,
                jeel.external_event_id,
                jeel.sync_status
            FROM journals j
            LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id
            LEFT JOIN calendars c ON jci.calendar_id = c.id
            LEFT JOIN journal_external_event_links jeel ON
                j.id = jeel.journal_id AND jci.calendar_id = jeel.calendar_id
            WHERE j.id = :journal_id
        """)
        result = await session.execute(stmt, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            logger.info("Journal not found", journal_id=journal_id)
            return {"status": "ignored", "reason": "journal_not_found"}

        if not row.calendar_id:
            logger.info(
                "Journal is not an EVENT or has no calendar", journal_id=journal_id
            )
            return {"status": "ignored", "reason": "not_event_journal"}

        if not row.is_synced_to_google:
            logger.info(
                "Journal's calendar is not synced to Google",
                journal_id=journal_id,
                calendar_id=row.calendar_id,
            )
            return {"status": "ignored", "reason": "calendar_not_synced"}

        if event_type == "JournalUpdated":
            changed_fields = event_data.get("changed_fields", {})
            sync_relevant_fields = {
                "title",
                "content",
                "event_date_range",
                "calendar_info",
            }
            if not any(
                k.startswith(tuple(sync_relevant_fields)) for k in changed_fields.keys()
            ):
                logger.info("No sync-relevant fields changed", journal_id=journal_id)
                return {"status": "ignored", "reason": "no_op_update"}

        auth_stmt = text("""
            SELECT google_account_email
            FROM user_google_integration
            WHERE user_id = :user_id
            LIMIT 1
        """)
        auth_result = await session.execute(auth_stmt, {"user_id": row.user_id})
        auth_row = auth_result.fetchone()

        if not auth_row:
            logger.warning(
                "No Google integration found for user",
                user_id=row.user_id,
                journal_id=journal_id,
            )
            return {"status": "ignored", "reason": "no_google_integration"}

        google_account_email = auth_row.google_account_email

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
            user_id=row.user_id,
        )

        event_payload = {
            "summary": row.title or "Untitled Event",
            "description": row.content or "",
        }
        if row.location:
            event_payload["location"] = row.location

        if row.is_all_day:
            start_date = row.event_date_range_start.date().isoformat()
            end_date = row.event_date_range_end.date() + timedelta(days=1)
            event_payload["start"] = {"date": start_date}
            event_payload["end"] = {"date": end_date.isoformat()}
        else:
            event_payload["start"] = {
                "dateTime": row.event_date_range_start.isoformat()
            }
            event_payload["end"] = {"dateTime": row.event_date_range_end.isoformat()}

        # Fetch and prune any orphaned links from other calendars (e.g. if the journal was moved)
        links_stmt = text("""
            SELECT jeel.external_event_id, c.google_calendar_id, jeel.calendar_id
            FROM journal_external_event_links jeel
            JOIN calendars c ON jeel.calendar_id = c.id
            WHERE jeel.journal_id = :journal_id
        """)
        links_result = await session.execute(links_stmt, {"journal_id": journal_id})
        existing_links = links_result.fetchall()
        from googleapiclient.errors import HttpError

        for link_row in existing_links:
            if link_row.calendar_id != row.calendar_id:
                if not link_row.external_event_id:
                    del_link_stmt = text("""
                        DELETE FROM journal_external_event_links
                        WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                    """)
                    await session.execute(
                        del_link_stmt,
                        {"journal_id": journal_id, "calendar_id": link_row.calendar_id},
                    )
                    continue

                success = False
                try:
                    del_cal_id = link_row.google_calendar_id or "primary"
                    await client.delete_event(link_row.external_event_id, del_cal_id)
                    success = True
                    logger.info(
                        "Deleted orphaned journal event from old Google Calendar",
                        journal_id=journal_id,
                        old_calendar_id=link_row.calendar_id,
                    )
                except HttpError as e:
                    if e.resp.status in (404, 410):
                        success = True
                    else:
                        logger.warning(
                            "HTTP error deleting orphaned journal event",
                            error=str(e),
                            journal_id=journal_id,
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to delete orphaned journal event",
                        error=str(e),
                        journal_id=journal_id,
                    )

                if success:
                    del_link_stmt = text("""
                        DELETE FROM journal_external_event_links
                        WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                    """)
                    await session.execute(
                        del_link_stmt,
                        {"journal_id": journal_id, "calendar_id": link_row.calendar_id},
                    )
                else:
                    err_link_stmt = text("""
                        UPDATE journal_external_event_links
                        SET sync_status = 'errored', updated_at = now()
                        WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                    """)
                    await session.execute(
                        err_link_stmt,
                        {"journal_id": journal_id, "calendar_id": link_row.calendar_id},
                    )

        await session.commit()

        external_event_id = row.external_event_id
        target_calendar_id = row.google_calendar_id or "primary"

        if not external_event_id:
            lock_stmt = text("""
                INSERT INTO journal_external_event_links (
                    journal_id, calendar_id, sync_capability, sync_status, created_at, updated_at
                ) VALUES (
                    :journal_id, :calendar_id, 'outbound', 'syncing', now(), now()
                )
                ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                    sync_status = 'syncing', updated_at = now()
                WHERE journal_external_event_links.external_event_id IS NULL
                  AND journal_external_event_links.sync_status != 'syncing'
                RETURNING 1
            """)
            lock_result = await session.execute(
                lock_stmt, {"journal_id": journal_id, "calendar_id": row.calendar_id}
            )
            if lock_result.fetchone():
                await session.commit()
                action = "create"
            else:
                check_stmt = text("""
                    SELECT external_event_id FROM journal_external_event_links
                    WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                """)
                check_result = await session.execute(
                    check_stmt,
                    {"journal_id": journal_id, "calendar_id": row.calendar_id},
                )
                check_row = check_result.fetchone()
                if check_row and check_row.external_event_id:
                    external_event_id = check_row.external_event_id
                    action = "update"
                else:
                    logger.info(
                        "Another job is currently creating this event link, skipping to avoid duplicates",
                        journal_id=journal_id,
                    )
                    return {"status": "ignored", "reason": "concurrent_create"}
        else:
            action = "update"
        api_result = None

        try:
            if action == "create":
                api_result = await client.create_event(
                    event_payload, calendar_id=target_calendar_id
                )
                external_event_id = api_result.get("id")
            elif action == "update":
                api_result = await client.update_event(
                    external_event_id, event_payload, calendar_id=target_calendar_id
                )
            link_stmt = text("""
                INSERT INTO journal_external_event_links (
                    journal_id, calendar_id, external_event_id, external_version,
                    sync_capability, sync_status, created_at, updated_at
                ) VALUES (
                    :journal_id, :calendar_id, :external_event_id, :external_version,
                    'outbound', 'synced', now(), now()
                )
                ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                    external_event_id = EXCLUDED.external_event_id,
                    external_version = EXCLUDED.external_version,
                    sync_status = 'synced',
                    updated_at = now()
            """)
            await session.execute(
                link_stmt,
                {
                    "journal_id": journal_id,
                    "calendar_id": row.calendar_id,
                    "external_event_id": external_event_id,
                    "external_version": api_result.get("etag") if api_result else None,
                },
            )
            await session.commit()

            duration = (datetime.now(UTC) - started_at).total_seconds()
            logger.info(
                "Successfully pushed journal event to Google",
                journal_id=journal_id,
                action=action,
            )
            return {
                "status": "success",
                "action": action,
                "journal_id": journal_id,
                "external_event_id": external_event_id,
                "duration_seconds": duration,
            }

        except Exception:
            # Update link status to errored on failure
            link_stmt = text("""
                INSERT INTO journal_external_event_links (
                    journal_id, calendar_id, sync_capability, sync_status, created_at, updated_at
                ) VALUES (
                    :journal_id, :calendar_id, 'outbound', 'errored', now(), now()
                )
                ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                    sync_status = 'errored',
                    updated_at = now()
            """)
            await session.execute(
                link_stmt,
                {
                    "journal_id": journal_id,
                    "calendar_id": row.calendar_id,
                },
            )
            await session.commit()
            raise


async def process_journal_event(
    ctx: dict[str, Any], event_type: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Process a single journal event for Google Calendar synchronization.

    This ARQ task receives domain events (JournalCreated, JournalUpdated, JournalDeleted)
    and pushes them to Google Calendar if the journal's calendar is synced.

    Args:
        ctx: ARQ context dictionary
        event_type: The type of the event (JournalCreated, JournalUpdated, JournalDeleted)
        event_data: The event payload containing journal_id, changed_fields, and for deletions, external_identifiers

    Returns:
        Task result dictionary with sync status
    """
    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    # Extract journal ID from event logic
    journal_id = event_data.get("journal_id")
    if not journal_id:
        logger.error(
            "Journal event missing journal_id", event_type=event_type, job_id=job_id
        )
        return {"status": "error", "error": "Missing journal_id"}

    logger.info(
        "Processing journal event",
        job_id=job_id,
        event_type=event_type,
        journal_id=journal_id,
    )

    started_at = datetime.now(UTC)
    session_factory = ctx["session_factory"]

    try:
        journal_id = event_data["journal_id"]

        if event_type == "JournalDeleted":
            return await _process_journal_deleted_event(
                session_factory, event_data, journal_id
            )

        return await _process_journal_upsert_event(
            session_factory, event_type, event_data, journal_id, started_at
        )

    except Exception as e:
        logger.error(
            "Process journal event failed",
            job_id=job_id,
            journal_id=journal_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def process_tag_event(
    ctx: dict[str, Any], event_type: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Process tag events like renamed or deleted for Google Contacts.

    This ARQ task receives domain events (TagUpdated, TagDeleted)
    and updates the corresponding Contact Groups across all synced Google Accounts.

    Args:
        ctx: ARQ context dictionary
        event_type: The type of the event (TagUpdated, TagDeleted)
        event_data: The event payload
    """
    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)
    session_factory = ctx["session_factory"]

    logger.info(
        "Processing tag event",
        job_id=job_id,
        event_type=event_type,
    )

    processed_users = 0
    errors = []

    try:
        async with session_factory() as session:
            # Find all users with Google Integration
            auth_stmt = text("""
                SELECT user_id, google_account_email
                FROM user_google_integration
            """)
            auth_result = await session.execute(auth_stmt)
            users = auth_result.fetchall()

            for row in users:
                user_id = row.user_id
                google_account_email = row.google_account_email

                try:
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

                    # Fetch groups to map name dynamically to resourceName
                    forward_group_mapping = await _build_contact_group_mapping(client)
                    reverse_group_mapping = _build_reverse_group_mapping(
                        forward_group_mapping
                    )

                    if event_type == "TagDeleted":
                        path_str = event_data.get("tag_name")
                        if not path_str:
                            continue

                        resource_name = reverse_group_mapping.get(path_str)
                        if resource_name:
                            await client.delete_contact_group(resource_name)
                    elif event_type == "TagUpdated":
                        changed_fields = event_data.get("changed_fields", {})
                        if "full_path" in changed_fields:
                            old_path, new_path = changed_fields["full_path"]
                            resource_name = reverse_group_mapping.get(old_path)
                            if resource_name:
                                await client.update_contact_group(
                                    resource_name, new_path
                                )

                    processed_users += 1
                except Exception as e:
                    logger.error(
                        "Error processing tag event for user",
                        google_account_email=google_account_email,
                        event_type=event_type,
                        error=str(e),
                    )
                    errors.append(str(e))

            if errors:
                return {
                    "status": "partial_success",
                    "processed_users": processed_users,
                    "errors": errors,
                }

            return {"status": "success", "processed_users": processed_users}

    except Exception as e:
        logger.error(
            "Process tag event failed",
            job_id=job_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


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

            # Build group mapping for tag→membership push.
            # Fetch existing groups, reverse the mapping, and pre-create any
            # missing groups for local tags.
            forward_group_mapping = await _build_contact_group_mapping(client)
            reverse_group_mapping = _build_reverse_group_mapping(forward_group_mapping)

            # Collect all tag names across contacts with a single batch query.
            # Tags are loaded again per-contact in _load_full_contact, but we
            # need all unique names upfront to ensure groups exist before push.
            contact_ids = [c["id"] for c in contacts_to_push]
            tags_by_contact = await _load_tag_names_for_contacts_batch(
                session, contact_ids
            )
            all_tag_names: set[str] = set()
            for tag_list in tags_by_contact.values():
                all_tag_names.update(tag_list)

            # Ensure groups exist for all tags
            if all_tag_names:
                reverse_group_mapping = await _ensure_google_groups_exist(
                    client=client,
                    tag_names=list(all_tag_names),
                    existing_groups=reverse_group_mapping,
                )

            # Push contacts to Google
            push_result = await push_contacts_to_google(
                session=session,
                client=client,
                contacts=contacts_to_push,
                google_account_email=google_account_email,
                group_name_to_resource=reverse_group_mapping,
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
    import secrets

    jitter = secrets.SystemRandom().uniform(0.8, 1.2)
    delay_with_jitter = delay * jitter

    # Cap at 15 minutes (900 seconds)
    return float(min(delay_with_jitter, 900.0))


def _create_google_client(
    session: Any,
    user_id: str | int,
    google_account_email: str,
) -> GoogleAPIClient:
    """Create an authenticated Google API client for the given user.

    Extracts the repeated auth+client creation pattern used across tasks.
    """
    auth_service = GoogleAuthService(
        session=session,
        encryption_key=settings.encryption_key.get_secret_value(),
        google_client_id=settings.google_client_id,
        google_client_secret=settings.google_client_secret.get_secret_value(),
    )
    return GoogleAPIClient(
        auth_service=auth_service,
        google_account_email=google_account_email,
        google_client_id=settings.google_client_id,
        google_client_secret=settings.google_client_secret.get_secret_value(),
        user_id=user_id,
    )


async def _fetch_all_calendar_events(
    client: GoogleAPIClient,
    list_kwargs: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch all events for a calendar using pagination.

    Returns:
        Tuple of (all_raw_events, new_sync_token). The sync token
        comes from the final page's nextSyncToken, or None if absent.
    """
    all_raw_events: list[dict[str, Any]] = []
    new_sync_token = None
    page_token = None

    while True:
        page_kwargs = dict(list_kwargs)
        if page_token:
            page_kwargs["page_token"] = page_token
        events_response = await client.list_events(**page_kwargs)

        all_raw_events.extend(events_response.get("items", []))

        if "nextSyncToken" in events_response:
            new_sync_token = events_response["nextSyncToken"]

        page_token = events_response.get("nextPageToken")
        if not page_token:
            break

        import asyncio

        await asyncio.sleep(0.2)

    return all_raw_events, new_sync_token


async def _save_calendar_sync_token(
    session: Any,
    new_sync_token: str,
    user_id: str | int,
    google_account_email: str,
    google_calendar_id: str = "primary",
) -> None:
    """Persist a calendar sync token per-calendar using UPSERT semantics.

    Stores the sync token in the calendar_sync_tokens table, keyed by
    (user_id, google_account_email, google_calendar_id). This ensures each
    calendar gets its own sync token for proper incremental sync.
    """
    save_token_stmt = text("""
        INSERT INTO calendar_sync_tokens
            (user_id, google_account_email, google_calendar_id,
             sync_token, last_synced_at, created_at, updated_at)
        VALUES
            (:user_id, :email, :google_calendar_id,
             :sync_token, :now, :now, :now)
        ON CONFLICT (user_id, google_account_email, google_calendar_id)
        DO UPDATE SET
            sync_token = EXCLUDED.sync_token,
            last_synced_at = EXCLUDED.last_synced_at,
            updated_at = EXCLUDED.updated_at
    """)
    now = datetime.now(UTC)
    await session.execute(
        save_token_stmt,
        {
            "sync_token": new_sync_token,
            "now": now,
            "user_id": str(user_id),
            "email": google_account_email,
            "google_calendar_id": google_calendar_id,
        },
    )


async def _load_calendar_sync_token(
    session: Any,
    user_id: str | int,
    google_account_email: str,
    google_calendar_id: str = "primary",
) -> str | None:
    """Load a per-calendar sync token from the calendar_sync_tokens table.

    Returns None if no token exists for this calendar.
    """
    token_stmt = text("""
        SELECT sync_token
        FROM calendar_sync_tokens
        WHERE user_id = :user_id
        AND google_account_email = :email
        AND google_calendar_id = :google_calendar_id
    """)
    result = await session.execute(
        token_stmt,
        {
            "user_id": str(user_id),
            "email": google_account_email,
            "google_calendar_id": google_calendar_id,
        },
    )
    from typing import cast

    return cast(str | None, result.scalar())


async def sync_calendar_events(
    ctx: dict[str, Any],
    google_account_email: str,
    user_id: str | int,
    sync_type: str = "smart",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Sync Google Calendar events inbound to create journal outbox events.

    This ARQ task fetches events from Google Calendar for each synced calendar,
    classifies them (new/updated/unchanged), and creates outbox events for the
    backend to process into journals.

    Args:
        ctx: ARQ context dictionary
        google_account_email: Google account email to sync
        user_id: User ID who initiated the sync
        sync_type: Type of sync - "full", "incremental", or "smart" (default)

    Returns:
        Task result dictionary with sync status and metrics
    """
    from core_shared.models.outbox import OutboxEvent

    from calendar_models import GoogleEvent
    from event_transformer import GoogleEventTransformer
    from inbound_sync import InboundSyncAction, InboundSyncClassifier

    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    logger.info(
        "Starting inbound calendar events sync",
        job_id=job_id,
        google_account_email=google_account_email,
        user_id=user_id,
        sync_type=sync_type,
    )

    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)
    classifier = InboundSyncClassifier()
    transformer = GoogleEventTransformer()

    metrics: dict[str, Any] = {
        "events_processed": 0,
        "events_created": 0,
        "events_updated": 0,
        "events_skipped": 0,
        "errors": 0,
        "worker_id": settings.worker_id,
        "started_at": started_at.isoformat(),
    }

    try:
        async with session_factory() as session:
            client = _create_google_client(session, user_id, google_account_email)

            # Fetch synced calendars from DB
            cal_stmt = text("""
                SELECT c.id as calendar_id, c.google_calendar_id, c.is_synced_to_google
                FROM calendars c
                WHERE c.user_id = :user_id AND c.is_synced_to_google = true
            """)
            cal_result = await session.execute(cal_stmt, {"user_id": str(user_id)})
            synced_calendars = cal_result.fetchall()

            if not synced_calendars:
                logger.info(
                    "No synced calendars found",
                    google_account_email=google_account_email,
                )

            for cal_row in synced_calendars:
                if not cal_row.is_synced_to_google:
                    continue

                google_calendar_id = cal_row.google_calendar_id or "primary"
                calendar_id = cal_row.calendar_id

                # Get existing per-calendar sync token
                existing_sync_token = await _load_calendar_sync_token(
                    session, user_id, google_account_email, google_calendar_id
                )

                # Decide whether to use sync token or time_min
                use_sync_token = sync_type != "full" and existing_sync_token is not None

                list_kwargs: dict[str, Any] = {
                    "calendar_id": google_calendar_id,
                }
                if use_sync_token:
                    list_kwargs["sync_token"] = existing_sync_token
                else:
                    # Full sync: fetch events from 10 years ago
                    time_min = (datetime.now(UTC) - timedelta(days=3650)).isoformat()
                    list_kwargs["time_min"] = time_min

                # Fetch all events with pagination
                all_raw_events, new_sync_token = await _fetch_all_calendar_events(
                    client, list_kwargs
                )

                # Process each event
                calendar_errors = 0
                for raw_event in all_raw_events:
                    try:
                        google_event = GoogleEvent.from_api_response(raw_event)

                        # Lookup existing link
                        link_stmt = text("""
                            SELECT journal_id, external_event_id, external_version,
                                   sync_capability, sync_status
                            FROM journal_external_event_links
                            WHERE calendar_id = :calendar_id
                            AND external_event_id = :external_event_id
                        """)
                        link_result = await session.execute(
                            link_stmt,
                            {
                                "calendar_id": calendar_id,
                                "external_event_id": google_event.id,
                            },
                        )
                        existing_link = link_result.fetchone()

                        # Classify the event
                        action = classifier.classify_inbound_event(
                            google_event=google_event,
                            existing_link=existing_link,
                        )

                        if action == InboundSyncAction.SKIP_UNCHANGED:
                            contact_relationships = (
                                transformer.extract_contact_relationships(google_event)
                            )
                            attendee_emails = [
                                r["email"] for r in contact_relationships
                            ]
                            if attendee_emails:
                                existing_journal_id = (
                                    existing_link.journal_id if existing_link else None
                                )
                                if existing_journal_id:
                                    check_stmt = text("""
                                        SELECT 1
                                        FROM contact_methods cm
                                        JOIN contacts c ON cm.contact_id = c.id
                                        WHERE cm.method_type = 'email'
                                          AND c.user_id = :user_id
                                          AND cm.value = ANY(:emails)
                                          AND NOT EXISTS (
                                              SELECT 1
                                              FROM journal_contacts jc
                                              WHERE jc.contact_id = cm.contact_id
                                                AND jc.journal_id = :journal_id
                                          )
                                        LIMIT 1
                                    """)
                                    check_result = await session.execute(
                                        check_stmt,
                                        {
                                            "user_id": str(user_id),
                                            "emails": attendee_emails,
                                            "journal_id": existing_journal_id,
                                        },
                                    )
                                    if check_result.fetchone():
                                        action = InboundSyncAction.UPDATE_JOURNAL

                        if action in (
                            InboundSyncAction.SKIP_UNCHANGED,
                            InboundSyncAction.SKIP_ONE_WAY,
                            InboundSyncAction.SKIP_CANCELLED,
                        ):
                            metrics["events_skipped"] += 1
                            continue

                        # Handle cancellation: mark linked journal as cancelled
                        if action == InboundSyncAction.CANCEL_JOURNAL:
                            existing_journal_id = (
                                existing_link.journal_id if existing_link else None
                            )
                            outbox_event = OutboxEvent.create_journal_sync_event(
                                journal_data={},
                                calendar_info_data={},
                                integration_source="google",
                                external_event_id=google_event.id,
                                calendar_id=str(calendar_id),
                                sync_action="cancelled",
                                etag=google_event.etag,
                                existing_journal_id=existing_journal_id,
                                contact_relationships=[],
                            )
                            session.add(outbox_event)
                            metrics["events_cancelled"] = (
                                metrics.get("events_cancelled", 0) + 1
                            )
                            metrics["events_processed"] += 1
                            continue

                        import uuid

                        transform_result = transformer.transform_event(
                            google_event,
                            str(user_id),
                            uuid.UUID(str(calendar_id)),
                            self_email=google_account_email,
                        )
                        if transform_result is None:
                            metrics["events_skipped"] += 1
                            continue

                        journal, calendar_info = transform_result

                        # Build journal data dict for outbox
                        journal_data = {
                            "title": journal.title,
                            "content": journal.content,
                            "event_date_range_start": journal.event_date_range.start.isoformat(),
                            "event_date_range_end": journal.event_date_range.end.isoformat(),
                            "user_id": str(user_id),
                        }
                        calendar_info_data = {
                            "calendar_id": str(calendar_id),
                            "is_all_day": calendar_info.is_all_day,
                            "location": calendar_info.location,
                            "start_time": calendar_info.start_time.isoformat()
                            if calendar_info.start_time
                            else None,
                            "end_time": calendar_info.end_time.isoformat()
                            if calendar_info.end_time
                            else None,
                            "event_state": calendar_info.event_state.value
                            if hasattr(calendar_info.event_state, "value")
                            else calendar_info.event_state,
                        }

                        # Extract attendee emails as contact relationships
                        contact_relationships = (
                            transformer.extract_contact_relationships(google_event)
                        )

                        # Determine sync action string
                        if action == InboundSyncAction.CREATE_JOURNAL:
                            sync_action = "created"
                            metrics["events_created"] += 1
                        elif action == InboundSyncAction.UPDATE_JOURNAL:
                            sync_action = "updated"
                            metrics["events_updated"] += 1
                        else:
                            metrics["events_skipped"] += 1
                            continue

                        existing_journal_id = (
                            existing_link.journal_id if existing_link else None
                        )

                        # Create outbox event
                        outbox_event = OutboxEvent.create_journal_sync_event(
                            journal_data=journal_data,
                            calendar_info_data=calendar_info_data,
                            integration_source="google",
                            external_event_id=google_event.id,
                            calendar_id=str(calendar_id),
                            sync_action=sync_action,
                            etag=google_event.etag,
                            existing_journal_id=existing_journal_id,
                            contact_relationships=contact_relationships,
                        )
                        session.add(outbox_event)
                        metrics["events_processed"] += 1

                    except Exception as e:
                        logger.error(
                            "Failed to process inbound calendar event",
                            event_id=raw_event.get("id"),
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        metrics["errors"] += 1
                        calendar_errors += 1

                # Save sync token only when this calendar processed without errors
                if new_sync_token and calendar_errors == 0:
                    await _save_calendar_sync_token(
                        session,
                        new_sync_token,
                        user_id,
                        google_account_email,
                        google_calendar_id,
                    )
                elif new_sync_token and calendar_errors > 0:
                    logger.warning(
                        "Skipping sync token save due to processing errors",
                        calendar_errors=calendar_errors,
                        google_calendar_id=google_calendar_id,
                        google_account_email=google_account_email,
                    )

            await session.commit()

        duration = (datetime.now(UTC) - started_at).total_seconds()
        metrics["completed_at"] = datetime.now(UTC).isoformat()
        metrics["duration_seconds"] = duration

        logger.info(
            "Inbound calendar events sync completed",
            job_id=job_id,
            google_account_email=google_account_email,
            **metrics,
        )

        # Record observability metrics
        metrics_collector.record_job_duration(
            job_type="calendar_sync", status="success", duration=duration
        )
        metrics_collector.increment_job_total(
            job_type="calendar_sync", status="success"
        )
        metrics_collector.increment_items_processed(
            sync_type="calendar_inbound",
            action="created",
            count=metrics["events_created"],
        )
        metrics_collector.increment_items_processed(
            sync_type="calendar_inbound",
            action="updated",
            count=metrics["events_updated"],
        )
        if metrics["errors"] > 0:
            metrics_collector.increment_sync_errors(
                sync_type="calendar_inbound", error_type="processing_error"
            )

        return {"status": "success", **metrics}

    except Exception as e:
        duration = (datetime.now(UTC) - started_at).total_seconds()
        logger.error(
            "Inbound calendar events sync failed",
            job_id=job_id,
            google_account_email=google_account_email,
            error=str(e),
            error_type=type(e).__name__,
            duration_seconds=duration,
        )
        # Record failure metrics
        metrics_collector.record_job_duration(
            job_type="calendar_sync", status="error", duration=duration
        )
        metrics_collector.increment_job_total(job_type="calendar_sync", status="error")
        metrics_collector.increment_sync_errors(
            sync_type="calendar_inbound", error_type=type(e).__name__
        )
        return {
            "status": "error",
            "google_account_email": google_account_email,
            "error": str(e),
            "error_type": type(e).__name__,
            "worker_id": settings.worker_id,
            "failed_at": datetime.now(UTC).isoformat(),
        }


async def setup_calendar_webhook(
    ctx: dict[str, Any],
    google_account_email: str,
    user_id: str | int,
    google_calendar_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Set up a Google Calendar push notification channel for a calendar.

    Registers a webhook with Google Calendar API and persists the channel
    metadata in the calendar_sync_tokens table.
    """
    import uuid

    logger.info(
        "Setting up calendar webhook",
        google_account_email=google_account_email,
        google_calendar_id=google_calendar_id,
        user_id=user_id,
    )

    if not settings.webhook_base_url:
        logger.warning(
            "webhook_base_url not configured, skipping webhook setup",
            google_account_email=google_account_email,
            google_calendar_id=google_calendar_id,
        )
        return {"status": "skipped", "reason": "webhook_base_url not configured"}

    session_factory = ctx["session_factory"]
    channel_id = str(uuid.uuid4())
    webhook_url = f"{settings.webhook_base_url.rstrip('/')}/api/integrations/google/calendar/webhook"

    try:
        async with session_factory() as session:
            client = _create_google_client(session, user_id, google_account_email)

            # Stop existing channel if one exists
            stmt = text("""
                SELECT channel_id, channel_resource_id
                FROM calendar_sync_tokens
                WHERE user_id = :user_id
                AND google_account_email = :email
                AND google_calendar_id = :google_calendar_id
                AND channel_id IS NOT NULL
                AND channel_resource_id IS NOT NULL
            """)
            existing_result = await session.execute(
                stmt,
                {
                    "user_id": str(user_id),
                    "email": google_account_email,
                    "google_calendar_id": google_calendar_id,
                },
            )
            existing_row = existing_result.fetchone()
            if existing_row:
                try:
                    await client.stop_channel(
                        channel_id=existing_row.channel_id,
                        resource_id=existing_row.channel_resource_id,
                    )
                    logger.info(
                        "Stopped previous calendar webhook channel",
                        channel_id=existing_row.channel_id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to stop previous watch channel",
                        channel_id=existing_row.channel_id,
                        error=str(e),
                    )

            # Register watch channel with Google
            result = await client.watch_events(
                calendar_id=google_calendar_id,
                channel_id=channel_id,
                webhook_url=webhook_url,
            )

            resource_id = result.get("resourceId", "")
            if not resource_id:
                logger.error(
                    "Google watch response missing resourceId",
                    calendar_id=google_calendar_id,
                    channel_id=channel_id,
                )
                return {
                    "status": "error",
                    "error": "Google watch response missing resourceId",
                }
            expiration_ms = result.get("expiration")
            channel_expiration = None
            if expiration_ms:
                channel_expiration = datetime.fromtimestamp(
                    int(expiration_ms) / 1000, tz=UTC
                )

            # Persist channel metadata in calendar_sync_tokens
            upsert_stmt = text("""
                INSERT INTO calendar_sync_tokens
                    (user_id, google_account_email, google_calendar_id,
                     channel_id, channel_resource_id, channel_expiration,
                     created_at, updated_at)
                VALUES
                    (:user_id, :email, :google_calendar_id,
                     :channel_id, :resource_id, :channel_expiration,
                     :now, :now)
                ON CONFLICT (user_id, google_account_email, google_calendar_id)
                DO UPDATE SET
                    channel_id = EXCLUDED.channel_id,
                    channel_resource_id = EXCLUDED.channel_resource_id,
                    channel_expiration = EXCLUDED.channel_expiration,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now(UTC)
            await session.execute(
                upsert_stmt,
                {
                    "user_id": str(user_id),
                    "email": google_account_email,
                    "google_calendar_id": google_calendar_id,
                    "channel_id": channel_id,
                    "resource_id": resource_id,
                    "channel_expiration": channel_expiration,
                    "now": now,
                },
            )
            await session.commit()

        logger.info(
            "Calendar webhook setup complete",
            channel_id=channel_id,
            resource_id=resource_id,
            channel_expiration=channel_expiration.isoformat()
            if channel_expiration
            else None,
            google_calendar_id=google_calendar_id,
        )

        return {
            "status": "success",
            "channel_id": channel_id,
            "resource_id": resource_id,
            "channel_expiration": channel_expiration.isoformat()
            if channel_expiration
            else None,
        }

    except Exception as e:
        logger.error(
            "Failed to setup calendar webhook",
            google_account_email=google_account_email,
            google_calendar_id=google_calendar_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
        }


# ARQ Worker Settings
class GoogleWorkerSettings(WorkerSettingsBase):
    """ARQ worker configuration."""

    # Task functions
    functions = [
        sync_google_contacts,
        push_local_contacts_to_google,
        process_journal_event,
        process_tag_event,
        sync_calendar_events,
        setup_calendar_webhook,
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
