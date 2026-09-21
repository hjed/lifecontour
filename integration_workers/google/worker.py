#!/usr/bin/env python3
"""
Google Contacts Integration Worker.

This worker processes Google Contacts synchronization tasks using ARQ.
It runs as a separate process from the main FastAPI application.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from arq import run_worker
from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared import (
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    generate_cron_jobs,
    generate_interval_cron,
    redis_settings_from_url,
)

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
from core_shared.models.history import Provenance
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
)
from core_shared.models.journals import CalendarInfo
from core_shared.models.outbox import OutboxEvent
from core_shared.models.sync_metadata import SyncStatus
from core_shared.repositories import (
    ActiveCalendarChannel,
    CalendarWatchRenewal,
    CalendarWatchRepository,
    SyncJobRepository,
)
from core_shared.telemetry import setup_telemetry, trace_arq_job
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Import from the installed core_shared package
from api_models import ListConnectionsResponse

# Import worker-specific services
from event_transformer import google_event_times
from google_auth_service import GoogleAuthService, GoogleAuthTokensNotFoundError
from google_client import (
    GoogleAPIClient,
    google_error_reasons,
    is_event_type_restriction,
    is_permission_denied,
)
from google_settings import GoogleSettings
from group_mapping import _build_contact_group_mapping
from group_translator import GoogleGroupNameTranslator
from transformer import GoogleContactTransformer

# Global settings instance
settings = GoogleSettings()

# Configure structured logging using shared module
configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)

# The provenance a journal domain event carries when the Google inbound sync
# is what applied it. Derived from the enum rather than spelled out, so a
# rename of the provenance value cannot silently disable the echo guard.
INBOUND_SYNC_SOURCE = Provenance.GOOGLE_CALENDAR.value

# The contacts equivalent: the inbound contacts sync applies Google's data
# through the backend's ContactService, which re-publishes the same contact
# events this worker consumes. Pushing those back out would write Google's own
# data to Google once per sub-entity it touched (LOCAL-177).
INBOUND_CONTACT_SYNC_SOURCE = Provenance.GOOGLE_CONTACTS.value

# Initialize metrics collector for this worker
metrics_collector = MetricsCollector(worker_type="google")


async def _run_stream_consumer(session_factory: Any, worker_settings: Any) -> None:
    """Adapt the Google stream consumer to the shared lifecycle factory's shape.

    ``build_worker_lifecycle`` calls ``consumer_factory(session_factory, settings)``;
    ``run_google_stream_consumer`` takes ``redis_url``/``stream_name`` keywords, so
    this thin closure reads them off the worker settings.
    """
    from stream_consumer_tasks import run_google_stream_consumer

    await run_google_stream_consumer(
        session_factory=session_factory,
        redis_url=worker_settings.redis_url,
        stream_name=worker_settings.stream_name,
    )


# Shared lifecycle: build the database session factory, launch the stream
# consumer, and on shutdown cancel/reap it and dispose the session factory's
# engine (google closes the session factory; it does not log consumer errors
# via a done-callback).
_on_startup, _on_shutdown = build_worker_lifecycle(
    settings=settings,
    consumer_factory=_run_stream_consumer,
    close_session_factory=True,
    log_consumer_errors=False,
)


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
        company = company.strip() or None
    if job_title:
        job_title = job_title.strip() or None

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
    # Tag identity is case-insensitive locally (LOWER(name) unique index), so
    # match group names case-insensitively too. An exact-case match wins;
    # otherwise the first case-variant in sorted-name order wins, so the pick
    # is stable across Google API listing order when duplicate case-variant
    # groups exist.
    lower_name_to_resource: dict[str, str] = {}
    for name in sorted(group_name_to_resource):
        lower_name_to_resource.setdefault(name.lower(), group_name_to_resource[name])
    memberships = []
    for tag_name in tag_names:
        resource_name = group_name_to_resource.get(
            tag_name
        ) or lower_name_to_resource.get(tag_name.lower())
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
    # Group names are matched case-insensitively (lower(), matching the DB's
    # LOWER(name) tag identity): creating a case-variant duplicate group in
    # Google would produce duplicate case-variant tags on the next pull.
    existing_lower_names = {name.lower() for name in updated_mapping}

    for tag_name in tag_names:
        if tag_name.lower() in existing_lower_names:
            continue

        try:
            result = await client.create_contact_group(tag_name)
            resource_name = result.get("resourceName")
            if resource_name:
                updated_mapping[tag_name] = resource_name
                existing_lower_names.add(tag_name.lower())
                logger.info(
                    "Created Google Contact Group for local tag",
                    tag_name=tag_name,
                    resource_name=resource_name,
                )
        except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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

    # Entity types are written so this contact link stays consistent with the
    # canonical sync_metadata store; COALESCE on conflict means a writer that
    # omits them never clears existing values.
    stmt = text("""
        INSERT INTO sync_metadata
            (internal_id, integration_source, external_id, last_synced_at,
             version_hash, sync_status, internal_entity_type, external_entity_type,
             created_at, updated_at)
        VALUES
            (:internal_id, :integration_source, :external_id, :last_synced_at,
             :version_hash, :sync_status, :internal_entity_type,
             :external_entity_type, :created_at, :updated_at)
        ON CONFLICT (integration_source, external_id)
        DO UPDATE SET
            internal_id = EXCLUDED.internal_id,
            last_synced_at = EXCLUDED.last_synced_at,
            version_hash = EXCLUDED.version_hash,
            sync_status = EXCLUDED.sync_status,
            internal_entity_type = COALESCE(
                EXCLUDED.internal_entity_type, sync_metadata.internal_entity_type
            ),
            external_entity_type = COALESCE(
                EXCLUDED.external_entity_type, sync_metadata.external_entity_type
            ),
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
            "internal_entity_type": "contact",
            "external_entity_type": "person",
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
        except Exception as e:  # noqa: BLE001
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

            except Exception as e:  # noqa: BLE001
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
    created_count = 0
    updated_count = 0

    # Transform and serialize contacts, handling per-item failures
    transformer = await _create_transformer(client)
    serialized_contacts = _process_contacts_batch(
        contacts_response.connections,
        transformer,
        google_account_email,
        metrics,
    )

    # An incremental delta returns contacts added remotely since the last sync
    # as well as modified ones. Emit 'created' for contacts the backend has not
    # seen and 'updated' for known ones, mirroring the full-sync decision, so the
    # backend doesn't reject brand-new contacts as "Contact not found for update".
    batch_external_ids = [
        google_person.resource_name for google_person, _ in serialized_contacts
    ]
    existing_external_ids = await _find_existing_external_ids(
        session, batch_external_ids, "google"
    )

    # Process changed contacts using outbox pattern
    for google_person, contact_data in serialized_contacts:
        try:
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

            total_processed += 1
            if sync_type == "created":
                created_count += 1
            else:
                updated_count += 1
            metrics["contacts_processed"] += 1

        except Exception as e:  # noqa: BLE001
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
        contacts_created=created_count,
        contacts_updated=updated_count,
    )

    return {"contacts_created": created_count, "contacts_updated": updated_count}


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


@trace_arq_job
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

                except Exception as e:  # noqa: BLE001
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

                except Exception as e:  # noqa: BLE001
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

    except Exception as e:  # noqa: BLE001
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


@trace_arq_job
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

    except Exception as e:  # noqa: BLE001
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
        except Exception as update_error:  # noqa: BLE001
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


# Google's own ACL vocabulary for "no access at all", which is what we record
# for a calendar that has left the account's list entirely.
GOOGLE_NO_ACCESS_ROLE = "none"

NON_WRITABLE_ACCESS_ROLES = frozenset(
    {GOOGLE_NO_ACCESS_ROLE, "reader", "freeBusyReader"}
)


def is_read_only_calendar(access_role: str | None) -> bool:
    """Return True if Google grants no write access to this calendar.

    A calendar shared read-only still lists its events, so it syncs inbound
    like any other — but every write to it is refused. Each of the three
    places that writes to Google asks this before calling the API.

    A role we have never stored (``None``) or do not recognise counts as
    writable: a calendar we have not asked about must not silently stop
    syncing, and a write that turns out to be refused is handled as its own
    permanent skip.
    """
    return access_role in NON_WRITABLE_ACCESS_ROLES


async def _read_only_google_calendar_ids(session: Any, user_id: str | int) -> set[str]:
    """Return the user's Google calendar ids that refuse writes."""
    result = await session.execute(
        text("""
            SELECT google_calendar_id
            FROM calendars
            WHERE user_id = :user_id
              AND google_calendar_id IS NOT NULL
              AND access_role = ANY(:read_only_roles)
        """),
        {"user_id": str(user_id), "read_only_roles": list(NON_WRITABLE_ACCESS_ROLES)},
    )
    return {row.google_calendar_id for row in result}


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
            FROM user_google_auth
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

        read_only_calendars = await _read_only_google_calendar_ids(session, user_id)

        deleted_ids = []
        read_only_ids = []
        forbidden_ids = []
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

                if calendar_id in read_only_calendars:
                    # Deleting is a write like any other, and this calendar
                    # refuses them. The copy stays on Google; asking would
                    # only earn a 403.
                    logger.info(
                        "Skipping delete: calendar is read-only",
                        google_event_id=google_event_id,
                        google_calendar_id=calendar_id,
                        journal_id=journal_id,
                    )
                    read_only_ids.append(google_event_id)
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
                elif is_permission_denied(e):
                    # The account may not delete from this calendar. The copy
                    # stays on Google and no retry can change that, so the
                    # deletion is recorded as refused rather than failing the
                    # job and leaving the event to be attempted forever.
                    logger.warning(
                        "Not allowed to delete this event from Google Calendar",
                        google_event_id=google_event_id,
                        journal_id=journal_id,
                        error=str(e),
                    )
                    forbidden_ids.append(google_event_id)
                else:
                    logger.error(
                        "HTTP error deleting journal event from Google Calendar",
                        error=str(e),
                        journal_id=journal_id,
                    )
                    errors.append(str(e))
            except Exception as e:  # noqa: BLE001
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
            "read_only_event_ids": read_only_ids,
            "forbidden_event_ids": forbidden_ids,
        }


async def _mark_link_errored(session: Any, journal_id: int, calendar_id: Any) -> None:
    """Record that this journal's event did not reach the calendar.

    Upserts rather than updates because the push may have failed before any
    link row existed — a create that never got an id still has to leave the
    failure visible rather than nothing at all.
    """
    await session.execute(
        text("""
            INSERT INTO journal_external_event_links (
                journal_id, calendar_id, sync_capability, sync_status,
                created_at, updated_at
            ) VALUES (
                :journal_id, :calendar_id, :capability, :status, now(), now()
            )
            ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                sync_status = :status,
                updated_at = now()
        """),
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "capability": ExternalEventLinkSyncCapability.OUTBOUND.value,
            "status": ExternalEventLinkSyncStatus.ERRORED.value,
        },
    )
    await session.commit()


async def _process_journal_upsert_event(
    session_factory: Any,
    event_type: str,
    event_data: dict[str, Any],
    journal_id: int,
    started_at: datetime,
) -> dict[str, Any]:
    # A journal the Google inbound sync just applied came *from* Google, and
    # its external event link is written in the same transaction as the
    # journal — so by the time the event reaches here the push would take the
    # update branch and PATCH the event the journal was built from. Besides
    # being a wasted round trip on every imported event, Google refuses it for
    # the event types it derives itself: a contact-linked birthday accepts
    # almost no change and answers with eventTypeRestriction.
    if event_data.get("source") == INBOUND_SYNC_SOURCE:
        logger.debug(
            "Skipping outbound push: the Google inbound sync applied this",
            journal_id=journal_id,
            event_type=event_type,
        )
        return {"status": "ignored", "reason": "inbound_sync_echo"}

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
                jci.start_time,
                jci.end_time,
                jci.timezone,
                jci.location,
                jci.calendar_id,
                jci.private_description,
                us.timezone AS user_timezone,
                c.is_synced_to_google,
                c.google_calendar_id,
                c.access_role,
                jeel.external_event_id,
                jeel.sync_status
            FROM journals j
            LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id
            LEFT JOIN user_settings us ON us.user_id = j.user_id
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

        # Skip outbound push for read-only calendars (shared calendars
        # where the user doesn't have write access)
        if is_read_only_calendar(row.access_role):
            logger.info(
                "Skipping outbound sync: calendar is read-only",
                journal_id=journal_id,
                calendar_id=row.calendar_id,
                access_role=row.access_role,
            )
            return {"status": "ignored", "reason": "read_only_calendar"}

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
            FROM user_google_auth
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
        }
        if not row.private_description:
            event_payload["description"] = row.content or ""
        if row.location:
            event_payload["location"] = row.location

        # The stored bounds are UTC instants of local midnight, so the date an
        # all-day event falls on is read in the event's own zone, else the
        # user's configured one, else UTC. A timed event's clock times are
        # only anchored in the zone the row itself records: an imported
        # event's times are local to the Google event's zone, which older
        # rows never stored, and re-anchoring them in the user's zone would
        # move the event. Without a zone the stored instants are pushed as
        # they are.
        timezone = row.timezone
        if row.is_all_day and not timezone:
            timezone = row.user_timezone
        calendar_info = CalendarInfo(
            calendar_id=row.calendar_id,
            journal_id=row.journal_id,
            start_time=row.start_time,
            end_time=row.end_time,
            is_all_day=bool(row.is_all_day),
            timezone=timezone,
            validate=False,
        )
        event_payload["start"], event_payload["end"] = google_event_times(
            row.event_date_range_start, row.event_date_range_end, calendar_info
        )

        # Fetch and prune any orphaned links from other calendars (e.g. if the
        # journal was moved).
        #
        # Pruning deletes the event from that calendar in Google, which is
        # right for an event *we* put there: the journal has moved on, and the
        # copy this push created is left behind. Those are exactly the links
        # this push writes, and it never records an identity token on them.
        #
        # A link the *inbound* sync has touched is the opposite: it exists
        # because that calendar returned the event, so the event is there
        # independently of anything we pushed, and deleting it would destroy
        # something real on the user's other calendar. Since de-duplication
        # that is the ordinary shape of an event held by two calendars.
        #
        # Two marks record that, and a link needs neither to be spared:
        #
        # - ``sync_capability = 'bidirectional'`` is written only by the
        #   inbound link writer, and never changed afterwards.
        # - ``external_identity`` is written only when the inbound sync
        #   matched the link to an event by identity.
        #
        # Both are needed. A token alone would not do: tokens arrive by
        # backfill on a calendar's next poll, and an event with no iCalUID
        # never gets one — so a real, inbound-created link can carry none.
        # And the capability alone would not do either: a link this push
        # created stays ``'outbound'`` even after the inbound sync later
        # matches it and gives it a token.
        #
        # The rule is about the link's own marks rather than whether a
        # sibling link shares its token: reassigning a journal's calendar
        # deletes the *old* calendar's link, and that is the sibling a shared
        # event was recognised by — a sibling comparison would lose the
        # protection in the same move that needs it most.
        links_stmt = text("""
            SELECT jeel.external_event_id,
                   c.google_calendar_id,
                   c.access_role,
                   jeel.calendar_id,
                   jeel.external_identity,
                   jeel.sync_capability
            FROM journal_external_event_links jeel
            JOIN calendars c ON jeel.calendar_id = c.id
            WHERE jeel.journal_id = :journal_id
        """)
        links_result = await session.execute(links_stmt, {"journal_id": journal_id})
        existing_links = links_result.fetchall()

        for link_row in existing_links:
            never_confirmed_upstream = (
                link_row.external_identity is None
                and link_row.sync_capability
                == ExternalEventLinkSyncCapability.OUTBOUND.value
            )
            if link_row.calendar_id != row.calendar_id and never_confirmed_upstream:
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

                if is_read_only_calendar(link_row.access_role):
                    # The event cannot be removed from a calendar we may not
                    # write to, so the link keeps recording that it is still
                    # out there rather than being dropped silently.
                    logger.info(
                        "Skipping orphan delete: calendar is read-only",
                        journal_id=journal_id,
                        old_calendar_id=link_row.calendar_id,
                        access_role=link_row.access_role,
                    )
                    await _mark_link_errored(session, journal_id, link_row.calendar_id)
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
                except Exception as e:  # noqa: BLE001
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
                    await _mark_link_errored(session, journal_id, link_row.calendar_id)

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

        except HttpError as e:
            await _mark_link_errored(session, journal_id, row.calendar_id)

            if is_event_type_restriction(e):
                # Google owns this event and derives it — a birthday from a
                # contact, an event from Gmail — so it accepts almost no
                # change. No retry and no reshaping of the payload makes the
                # same write land, so the message is acknowledged rather than
                # left pending to be redelivered until it dead-letters. The
                # journal keeps the local edit; the errored link is where the
                # divergence shows.
                logger.warning(
                    "Skipping outbound push: Google event type is not modifiable",
                    journal_id=journal_id,
                    external_event_id=external_event_id,
                    calendar_id=row.calendar_id,
                    error=str(e),
                )
                return {
                    "status": "ignored",
                    "reason": "event_type_not_modifiable",
                    "journal_id": journal_id,
                    "external_event_id": external_event_id,
                }

            if is_permission_denied(e):
                # Refusing the write is an answer, not a fault: the account
                # may not write to this calendar, or to this event. Raising
                # would ride the same retries to the same dead-letter for the
                # same reply, so the push stops here and the stored access
                # role is refreshed — a stale role is why the read-only guard
                # above let this push through at all.
                logger.warning(
                    "Google refused the outbound push, skipping this calendar",
                    journal_id=journal_id,
                    calendar_id=row.calendar_id,
                    google_calendar_id=target_calendar_id,
                    action=action,
                    error=str(e),
                )
                await _refresh_calendar_access_roles(session, client, row.user_id)
                return {
                    "status": "ignored",
                    "reason": "forbidden",
                    "journal_id": journal_id,
                    "action": action,
                }

            raise

        except Exception:
            await _mark_link_errored(session, journal_id, row.calendar_id)
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
                FROM user_google_auth
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
                except Exception as e:  # noqa: BLE001
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


async def _push_contact_to_google_for_event(
    session: AsyncSession,
    client: GoogleAPIClient,
    contact_id: int,
    sync_action: str,
    google_account_email: str,
    external_id: str | None,
    version_hash: str | None,
) -> dict[str, Any]:
    """Push a single contact to Google, triggered by a domain event.

    Loads full contact data, transforms to Google Person format, and
    creates or updates the contact via the Google People API.

    Args:
        session: Database session
        client: Google Contacts API client
        contact_id: Internal contact ID
        sync_action: "create" or "update"
        google_account_email: Google account email
        external_id: Google resource name (for updates)
        version_hash: ETag for optimistic concurrency (for updates)

    Returns:
        Result dict with status and resource details
    """
    contact: dict[str, Any] = {
        "id": contact_id,
        "sync_action": sync_action,
        "external_id": external_id,
        "version_hash": version_hash,
    }

    # Load base contact data from DB
    base_stmt = text("""
        SELECT first_name, last_name, middle_name, nick_name, is_favourite,
               company, job_title
        FROM contacts
        WHERE id = :contact_id
    """)
    base_result = await session.execute(base_stmt, {"contact_id": contact_id})
    base_row = base_result.fetchone()
    if not base_row:
        logger.warning(
            "Contact not found in database for push",
            contact_id=contact_id,
            google_account_email=google_account_email,
        )
        return {"status": "skipped", "reason": "contact_not_found"}

    contact["first_name"] = base_row.first_name
    contact["last_name"] = base_row.last_name
    contact["middle_name"] = base_row.middle_name
    contact["nick_name"] = base_row.nick_name
    contact["is_favourite"] = base_row.is_favourite
    contact["company"] = base_row.company if hasattr(base_row, "company") else None
    contact["job_title"] = (
        base_row.job_title if hasattr(base_row, "job_title") else None
    )

    # Load full contact data (methods, addresses, notes, tags, important_dates)
    full_data = await _load_full_contact(session, contact_id)
    contact.update(full_data)

    # Transform to Google Person format
    person_data = _transform_contact_to_google_person(contact)

    if sync_action == "create":
        result = await client.create_contact(person_data)
        await _upsert_sync_metadata(
            session=session,
            internal_id=contact_id,
            external_id=result["resourceName"],
            etag=result.get("etag"),
            integration_source="google",
        )
        logger.info(
            "Created contact in Google via event",
            contact_id=contact_id,
            resource_name=result["resourceName"],
        )
        return {"status": "created", "resource_name": result["resourceName"]}

    elif sync_action == "update":
        result = await client.update_contact(
            resource_name=external_id,  # type: ignore[arg-type]
            contact_data=person_data,
            etag=version_hash,
        )
        await _upsert_sync_metadata(
            session=session,
            internal_id=contact_id,
            external_id=result["resourceName"],
            etag=result.get("etag"),
            integration_source="google",
        )
        logger.info(
            "Updated contact in Google via event",
            contact_id=contact_id,
            resource_name=result["resourceName"],
        )
        return {"status": "updated", "resource_name": result["resourceName"]}

    return {"status": "skipped", "reason": f"unknown_sync_action_{sync_action}"}


async def _delete_contact_from_google_for_event(
    session: AsyncSession,
    client: GoogleAPIClient,
    contact_id: int | None,
    external_id: str,
    google_account_email: str,
) -> dict[str, Any]:
    """Delete a contact from Google, triggered by a domain event.

    Args:
        session: Database session
        client: Google Contacts API client
        contact_id: Internal contact ID (log context only; the merge path
            passes the absorbed source id)
        external_id: Google resource name
        google_account_email: Google account email

    Returns:
        Result dict with status
    """
    await client.delete_contact(resource_name=external_id)

    # Clean up sync metadata
    cleanup_stmt = text("""
        DELETE FROM sync_metadata
        WHERE integration_source = :integration_source
          AND external_id = :external_id
    """)
    await session.execute(
        cleanup_stmt,
        {"integration_source": "google", "external_id": external_id},
    )

    logger.info(
        "Deleted contact from Google via event",
        contact_id=contact_id,
        external_id=external_id,
        google_account_email=google_account_email,
    )
    return {"status": "deleted", "external_id": external_id}


async def _process_contact_merged_event(
    ctx: dict[str, Any], event_data: dict[str, Any]
) -> dict[str, Any]:
    """Reconcile a contact merge with Google Contacts (ITER13-005 Phase 2).

    The merge already re-pointed the survivor's external links and deleted the
    source contact's *local* ``external_references`` / ``sync_metadata`` inline
    (Phase 1). A same-service clash — both contacts linked to Google — is
    surfaced on ``event_data["external_collisions"]``; each entry carries the
    source contact's orphaned remote id (``source_external_id``), which is the
    only way to find it now that the local row is gone.

    For every google collision this deletes the source's remote Google contact
    via the existing delete flow (which also cleans any residual sync metadata
    and treats a remote 404 as success). The survivor's Google contact is
    reconciled separately by the ``ContactUpdated`` event the merge also emits,
    so it is intentionally not re-pushed here.

    Args:
        ctx: ARQ-compatible context dictionary with session_factory
        event_data: The ``ContactMerged`` payload (survivor/source ids +
            ``external_collisions``)

    Returns:
        Task result dictionary with reconciliation status
    """
    source_contact_id = event_data.get("source_contact_id")
    collisions = event_data.get("external_collisions") or []
    google_collisions = [c for c in collisions if c.get("external_system") == "google"]

    if not google_collisions:
        logger.info(
            "ContactMerged has no Google collisions, skipping",
            source_contact_id=source_contact_id,
        )
        return {"status": "skipped", "reason": "no_google_collisions"}

    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        # Find all Google integrations for all users. The source remote belongs
        # to one of them; deleting a non-existent resource on the others returns
        # a 404, which the client treats as success (mirrors ContactDeleted).
        auth_stmt = text("""
            SELECT user_id, google_account_email
            FROM user_google_auth
        """)
        auth_result = await session.execute(auth_stmt)
        users = auth_result.fetchall()

        if not users:
            logger.info(
                "No Google integrations found, skipping ContactMerged",
                source_contact_id=source_contact_id,
            )
            return {"status": "skipped", "reason": "no_google_integrations"}

        results = []
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

                for collision in google_collisions:
                    result = await _delete_contact_from_google_for_event(
                        session=session,
                        client=client,
                        contact_id=source_contact_id,
                        external_id=collision["source_external_id"],
                        google_account_email=google_account_email,
                    )
                    results.append(result)

                await session.commit()

            except Exception as e:
                logger.error(
                    "Failed to reconcile ContactMerged for Google account",
                    source_contact_id=source_contact_id,
                    google_account_email=google_account_email,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

        return {"status": "success", "results": results}


async def process_contact_event(
    ctx: dict[str, Any], event_type: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """Process a single contact event for Google Contacts outbound sync.

    Receives domain events (ContactCreated, ContactUpdated, ContactDeleted,
    ContactMerged) and pushes the changes to Google Contacts for all synced
    Google accounts.

    Args:
        ctx: ARQ-compatible context dictionary with session_factory
        event_type: The domain event type
        event_data: The event payload containing contact_id and changed_fields

    Returns:
        Task result dictionary with sync status
    """
    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    # Echo guard: skip anything the inbound contacts sync caused, before any
    # database work. It runs ahead of the ContactMerged branch so every consumed
    # contact event is covered by one check.
    if event_data.get("source") == INBOUND_CONTACT_SYNC_SOURCE:
        logger.debug(
            "Skipping contact event applied by the inbound Google sync",
            job_id=job_id,
            event_type=event_type,
            contact_id=event_data.get("contact_id"),
        )
        return {"status": "skipped", "reason": "inbound_echo"}

    # ContactMerged carries no contact_id (only survivor/source ids and the
    # external collisions to reconcile), so it is handled before the
    # contact_id guard below.
    if event_type == "ContactMerged":
        return await _process_contact_merged_event(ctx, event_data)

    contact_id = event_data.get("contact_id")
    if not contact_id:
        logger.error(
            "Contact event missing contact_id",
            event_type=event_type,
            job_id=job_id,
        )
        return {"status": "error", "error": "Missing contact_id"}

    logger.info(
        "Processing contact event",
        job_id=job_id,
        event_type=event_type,
        contact_id=contact_id,
    )

    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        # Look up sync metadata once — it's keyed by
        # (integration_source, internal_id) and is independent of which
        # Google account we push to.
        sync_stmt = text("""
            SELECT external_id, version_hash
            FROM sync_metadata
            WHERE integration_source = :integration_source
              AND internal_id = :internal_id
        """)
        sync_result = await session.execute(
            sync_stmt,
            {"integration_source": "google", "internal_id": contact_id},
        )
        sync_row = sync_result.fetchone()

        # Find all Google integrations for all users
        auth_stmt = text("""
            SELECT user_id, google_account_email
            FROM user_google_auth
        """)
        auth_result = await session.execute(auth_stmt)
        users = auth_result.fetchall()

        if not users:
            logger.info(
                "No Google integrations found, skipping contact event",
                contact_id=contact_id,
                event_type=event_type,
            )
            return {"status": "skipped", "reason": "no_google_integrations"}

        results = []
        for row in users:
            user_id = row.user_id
            google_account_email = row.google_account_email

            try:
                # Create Google API client
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

                if event_type == "ContactDeleted":
                    if not sync_row:
                        logger.info(
                            "No sync metadata for deleted contact, skipping",
                            contact_id=contact_id,
                            google_account_email=google_account_email,
                        )
                        results.append(
                            {"status": "skipped", "reason": "no_sync_metadata"}
                        )
                        continue

                    result = await _delete_contact_from_google_for_event(
                        session=session,
                        client=client,
                        contact_id=contact_id,
                        external_id=sync_row.external_id,
                        google_account_email=google_account_email,
                    )
                else:
                    # ContactCreated or ContactUpdated
                    if sync_row:
                        sync_action = "update"
                        external_id = sync_row.external_id
                        version_hash = sync_row.version_hash
                    else:
                        sync_action = "create"
                        external_id = None
                        version_hash = None

                    result = await _push_contact_to_google_for_event(
                        session=session,
                        client=client,
                        contact_id=contact_id,
                        sync_action=sync_action,
                        google_account_email=google_account_email,
                        external_id=external_id,
                        version_hash=version_hash,
                    )

                results.append(result)
                await session.commit()

            except Exception as e:
                logger.error(
                    "Failed to process contact event for Google account",
                    contact_id=contact_id,
                    google_account_email=google_account_email,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

        return {"status": "success", "results": results}


@trace_arq_job
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

    except Exception as e:  # noqa: BLE001
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

        await asyncio.sleep(0.2)

    return all_raw_events, new_sync_token


async def _find_journal_by_event_identity(
    session: Any,
    user_id: str | int,
    external_identity: str,
    calendar_id: Any,
) -> int | None:
    """Find the journal another calendar already holds for this same event.

    ``external_event_id`` is unique only within one calendar, so when a
    calendar we sync has been invited to an event owned by another calendar
    we sync, its copy looks brand new. The identity token is equal across
    those copies, so a hit here means the event is already journalled and
    this calendar needs a link to it rather than a journal of its own.

    Scoped to the user, because a token means nothing across accounts, and
    to *other* calendars, because a hit in this one would have been found by
    the per-calendar lookup already.
    """
    result = await session.execute(
        text("""
            SELECT l.journal_id
            FROM journal_external_event_links l
            JOIN calendars c ON c.id = l.calendar_id
            WHERE c.user_id = :user_id
              AND l.external_identity = :external_identity
              AND l.calendar_id <> :calendar_id
            ORDER BY l.created_at ASC, l.journal_id ASC
            LIMIT 1
        """),
        {
            "user_id": str(user_id),
            "external_identity": external_identity,
            "calendar_id": calendar_id,
        },
    )
    row = result.fetchone()
    return int(row.journal_id) if row else None


async def _fetch_calendar_access_roles(client: GoogleAPIClient) -> dict[str, str]:
    """Return Google's current access role for every calendar in the list."""
    roles: dict[str, str] = {}
    page_token: str | None = None

    while True:
        response = await client.list_calendars(page_token=page_token)
        for item in response.get("items", []):
            google_calendar_id = item.get("id")
            access_role = item.get("accessRole")
            if google_calendar_id and access_role:
                roles[google_calendar_id] = access_role
                if item.get("primary"):
                    roles.setdefault("primary", access_role)

        page_token = response.get("nextPageToken")
        if not page_token:
            return roles


async def _mark_vanished_calendars_unreachable(
    session: Any, user_id: str | int, seen: dict[str, str]
) -> int:
    """Record the calendars that are no longer in the account's list at all.

    Revoking a share does not return the calendar with a lesser role — Google
    drops it from ``calendarList`` entirely. Reconciling only the entries that
    came back would leave the last role we saw (often ``writer``) standing
    forever, and every later edit would go on earning a refusal, which is the
    very thing the refresh exists to stop.

    Only sound while the user has a single connected Google account:
    ``calendars`` records no account of its own, so with two connected
    accounts one account's list cannot speak for the other's calendars. With
    more than one, the absent calendars are left alone and a refused write
    remains their only signal.
    """
    if not seen:
        # A successful fetch that returned nothing tells us nothing about
        # which calendars are gone — treating it as "all of them" would
        # unsync the account on one odd response.
        return 0

    account_count = await session.execute(
        text("SELECT count(*) FROM user_google_auth WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    if account_count.scalar() != 1:
        return 0

    result = await session.execute(
        text("""
            UPDATE calendars
            SET access_role = :no_access, updated_at = now()
            WHERE user_id = :user_id
              AND google_calendar_id IS NOT NULL
              AND google_calendar_id <> ALL(:seen)
              AND access_role IS DISTINCT FROM :no_access
        """),
        {
            "user_id": str(user_id),
            "seen": list(seen),
            "no_access": GOOGLE_NO_ACCESS_ROLE,
        },
    )
    vanished = result.rowcount or 0
    if vanished:
        logger.info(
            "Calendars no longer reachable from this Google account",
            user_id=user_id,
            count=vanished,
        )
    return vanished


async def _refresh_calendar_access_roles(
    session: Any, client: GoogleAPIClient, user_id: str | int
) -> int:
    """Store Google's current access role on each of the user's calendars.

    The outbound push is skipped for calendars the account can only read, and
    that guard is only as good as the stored role. Google can change it at any
    time — a shared work calendar downgraded to "see all event details", an
    account that has left the organisation — and nothing tells us but the 403
    on the next write. Re-reading it from ``calendarList`` on every sync is
    what keeps the guard honest and lets a revoked permission settle by
    itself instead of costing a refused request per edit, forever.

    A calendar that has left the list entirely is handled too — see
    :func:`_mark_vanished_calendars_unreachable`.

    Returns the number of calendars whose stored role changed. Never raises:
    a list that cannot be fetched leaves the stored roles as they were rather
    than failing the sync or the push that asked for the refresh.

    Commits whatever it ran, including when nothing changed, so the caller is
    never left holding an open transaction to reason about.
    """
    try:
        roles = await _fetch_calendar_access_roles(client)
    except Exception as e:  # noqa: BLE001 - a stale role is better than a failed sync
        logger.warning(
            "Could not refresh calendar access roles",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return 0

    update_stmt = text("""
        UPDATE calendars
        SET access_role = :access_role, updated_at = now()
        WHERE user_id = :user_id
          AND google_calendar_id = :google_calendar_id
          AND access_role IS DISTINCT FROM :access_role
    """)

    changed = 0
    for google_calendar_id, access_role in roles.items():
        result = await session.execute(
            update_stmt,
            {
                "user_id": str(user_id),
                "google_calendar_id": google_calendar_id,
                "access_role": access_role,
            },
        )
        if result.rowcount:
            changed += 1
            logger.info(
                "Calendar access role changed",
                user_id=user_id,
                google_calendar_id=google_calendar_id,
                access_role=access_role,
            )

    changed += await _mark_vanished_calendars_unreachable(session, user_id, roles)

    await session.commit()

    return changed


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


def _iana_zone_name(value: object) -> str | None:
    """``value`` when it names a zone ``ZoneInfo`` can resolve, else ``None``.

    A stored setting is user input and a row column may be absent, so the
    name is checked before it is trusted anywhere a bad one would raise.
    """
    if not isinstance(value, str) or not value:
        return None
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(value)
    except Exception:  # noqa: BLE001
        return None
    return value


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


@trace_arq_job
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
    from event_identity import build_event_identity
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

            # Re-read what the account is allowed to do with each calendar
            # before syncing it. Outbound push relies on the stored role, and
            # this is the only moment we hear about a permission that changed
            # on Google's side.
            await _refresh_calendar_access_roles(session, client, user_id)

            # Fetch synced calendars from DB
            # The user's configured zone rides along on each calendar row so an
            # imported all-day event can be stored on the day the user reads
            # it as, without a separate lookup per sync.
            cal_stmt = text("""
                SELECT c.id as calendar_id, c.google_calendar_id, c.is_synced_to_google,
                       us.timezone AS user_timezone
                FROM calendars c
                LEFT JOIN user_settings us ON us.user_id = c.user_id
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
                user_timezone = _iana_zone_name(cal_row.user_timezone)

                # Get existing per-calendar sync token
                existing_sync_token = await _load_calendar_sync_token(
                    session, user_id, google_account_email, google_calendar_id
                )

                # Decide whether to use sync token or time_min
                use_sync_token = sync_type != "full" and existing_sync_token is not None

                list_kwargs: dict[str, Any] = {
                    "calendar_id": google_calendar_id,
                    "single_events": True,
                }

                time_min = (datetime.now(UTC) - timedelta(days=3650)).isoformat()

                if use_sync_token:
                    list_kwargs["sync_token"] = existing_sync_token
                else:
                    # Full sync: fetch events from 10 years ago indefinitely
                    list_kwargs["time_min"] = time_min

                # Fetch all events with pagination
                from googleapiclient.errors import HttpError

                try:
                    all_raw_events, new_sync_token = await _fetch_all_calendar_events(
                        client, list_kwargs
                    )
                except HttpError as e:
                    is_sync_token_error = e.resp.status == 410 or (
                        e.resp.status == 400
                        and "syncTokenInvalid" in google_error_reasons(e)
                    )
                    if is_sync_token_error:
                        logger.warning(
                            "Sync token invalid, falling back to full sync",
                            calendar_id=google_calendar_id,
                            error=str(e),
                        )
                        # Clear existing sync token and fallback to full sync
                        await session.execute(
                            text(
                                "UPDATE calendar_sync_tokens "
                                "SET sync_token = NULL "
                                "WHERE user_id = :user_id "
                                "AND google_account_email = :email "
                                "AND google_calendar_id = :google_calendar_id"
                            ),
                            {
                                "user_id": str(user_id),
                                "email": google_account_email,
                                "google_calendar_id": google_calendar_id,
                            },
                        )
                        await session.commit()

                        list_kwargs.pop("sync_token", None)
                        list_kwargs["time_min"] = time_min
                        (
                            all_raw_events,
                            new_sync_token,
                        ) = await _fetch_all_calendar_events(client, list_kwargs)
                    else:
                        raise

                # Process each event
                calendar_errors = 0
                for raw_event in all_raw_events:
                    try:
                        google_event = GoogleEvent.from_api_response(raw_event)

                        # Lookup existing link
                        link_stmt = text("""
                            SELECT journal_id, external_event_id, external_version,
                                   sync_capability, sync_status, recurring_event_id,
                                   external_identity
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

                        # A cancelled, unlinked event id may be a recurring
                        # MASTER id (Google reports whole-series deletion as a
                        # single cancelled master under singleEvents=true).
                        # Instances point at it via recurring_event_id.
                        has_series_links = False
                        if google_event.status == "cancelled" and existing_link is None:
                            # Match the backfilled recurring id, plus a prefix
                            # fallback for legacy links synced before the id
                            # was recorded (instance ids are <master>_<time>;
                            # the extra-underscore guard excludes successor
                            # series created by "this and following" edits).
                            escaped_master = (
                                google_event.id.replace("\\", "\\\\")
                                .replace("%", "\\%")
                                .replace("_", "\\_")
                            )
                            series_links_stmt = text("""
                                SELECT 1
                                FROM journal_external_event_links
                                WHERE calendar_id = :calendar_id
                                  AND (recurring_event_id = :recurring_event_id
                                       OR (recurring_event_id IS NULL
                                           AND external_event_id
                                               LIKE :instance_prefix ESCAPE '\\'
                                           AND external_event_id
                                               NOT LIKE :deeper_prefix ESCAPE '\\'))
                                LIMIT 1
                            """)
                            series_links_result = await session.execute(
                                series_links_stmt,
                                {
                                    "calendar_id": calendar_id,
                                    "recurring_event_id": google_event.id,
                                    "instance_prefix": f"{escaped_master}\\_%",
                                    "deeper_prefix": f"{escaped_master}\\_%\\_%",
                                },
                            )
                            has_series_links = series_links_result.scalar() is not None

                        # Classify the event
                        action = classifier.classify_inbound_event(
                            google_event=google_event,
                            existing_link=existing_link,
                            has_series_links=has_series_links,
                        )

                        # Cross-calendar de-dupe. When one calendar invites
                        # another, both copies are real events with their own
                        # ids, so the lookup above legitimately found nothing
                        # and this reads as a brand-new event. The identity
                        # token is what the two copies share: a hit means the
                        # event is already journalled, and this calendar wants
                        # a link to that journal rather than a journal of its
                        # own. Turning the create into an update is what gets
                        # the backend to add the second link.
                        external_identity = build_event_identity(google_event)
                        deduped_journal_id: int | None = None
                        if (
                            action == InboundSyncAction.CREATE_JOURNAL
                            and external_identity
                        ):
                            deduped_journal_id = await _find_journal_by_event_identity(
                                session,
                                user_id,
                                external_identity,
                                calendar_id,
                            )
                            if deduped_journal_id is not None:
                                logger.info(
                                    "Event already journalled from another "
                                    "calendar, linking instead of duplicating",
                                    external_event_id=google_event.id,
                                    journal_id=deduped_journal_id,
                                    calendar_id=str(calendar_id),
                                )
                                action = InboundSyncAction.UPDATE_JOURNAL
                                metrics["events_deduplicated"] = (
                                    metrics.get("events_deduplicated", 0) + 1
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
                                          AND cm.value = ANY(:emails)
                                          AND NOT EXISTS (
                                              SELECT 1
                                              FROM journal_contact_relationships jc
                                              WHERE jc.contact_id = cm.contact_id
                                                AND jc.journal_id = :journal_id
                                          )
                                        LIMIT 1
                                    """)
                                    check_result = await session.execute(
                                        check_stmt,
                                        {
                                            "emails": attendee_emails,
                                            "journal_id": existing_journal_id,
                                        },
                                    )
                                    if check_result.fetchone():
                                        action = InboundSyncAction.UPDATE_JOURNAL

                        # Backfill promotion: an unchanged recurring instance
                        # whose link predates the series feature (no stored
                        # recurring id) is re-synced once so the backend can
                        # record the id and create the series membership.
                        if (
                            action == InboundSyncAction.SKIP_UNCHANGED
                            and google_event.recurring_event_id
                            and existing_link is not None
                            and existing_link.recurring_event_id is None
                        ):
                            action = InboundSyncAction.UPDATE_JOURNAL

                        # Same, for links made before events carried an
                        # identity token. Nothing else would ever give them
                        # one — an unchanged event is skipped on its ETag —
                        # so the de-dupe would otherwise only work for events
                        # first synced after this shipped. Once the backend
                        # stores the token the link stops qualifying, so this
                        # fires once per link rather than every sync.
                        if (
                            action == InboundSyncAction.SKIP_UNCHANGED
                            and external_identity
                            and existing_link is not None
                            and existing_link.external_identity is None
                        ):
                            action = InboundSyncAction.UPDATE_JOURNAL

                        if action in (
                            InboundSyncAction.SKIP_UNCHANGED,
                            InboundSyncAction.SKIP_ONE_WAY,
                            InboundSyncAction.SKIP_CANCELLED,
                        ):
                            metrics["events_skipped"] += 1
                            continue

                        # Whole-series deletion: fan out to the backend, which
                        # deletes far-future untouched instances and cancels
                        # the rest.
                        if action == InboundSyncAction.CANCEL_SERIES:
                            outbox_event = (
                                OutboxEvent.create_journal_series_cancelled_event(
                                    integration_source="google",
                                    calendar_id=str(calendar_id),
                                    recurring_event_id=google_event.id,
                                )
                            )
                            session.add(outbox_event)
                            metrics["series_cancellations"] = (
                                metrics.get("series_cancellations", 0) + 1
                            )
                            metrics["events_processed"] += 1
                            continue

                        # Handle cancellation: mark linked journal as cancelled
                        # BUT skip if the event's end date is in the past — some calendars
                        # (e.g. shared/subscribed) don't preserve past events and return
                        # them as cancelled during incremental sync even though they already
                        # happened.
                        if action == InboundSyncAction.CANCEL_JOURNAL:
                            existing_journal_id = (
                                existing_link.journal_id if existing_link else None
                            )

                            # Check if the event already ended (past event)
                            # Use a 1-day buffer to avoid edge cases with all-day
                            # events where event_date_range_end is midnight-normalised.
                            if existing_journal_id is not None:
                                end_date_stmt = text("""
                                    SELECT event_date_range_end
                                    FROM journals
                                    WHERE id = :journal_id
                                """)
                                end_date_result = await session.execute(
                                    end_date_stmt,
                                    {"journal_id": existing_journal_id},
                                )
                                event_end_date = end_date_result.scalar()

                                if (
                                    event_end_date is not None
                                    and event_end_date
                                    < datetime.now(UTC) - timedelta(days=1)
                                ):
                                    logger.info(
                                        "Skipping cancellation for past event",
                                        external_event_id=google_event.id,
                                        journal_id=existing_journal_id,
                                        event_end_date=event_end_date.isoformat(),
                                    )
                                    metrics["events_skipped"] += 1
                                    continue

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
                                recurring_event_id=google_event.recurring_event_id,
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
                            all_day_timezone=user_timezone,
                        )
                        if transform_result is None:
                            metrics["events_skipped"] += 1
                            continue

                        journal, calendar_info = transform_result

                        # Build journal data dict for outbox
                        journal_data = {
                            "title": journal.title,
                            "event_date_range_start": journal.event_date_range.start.isoformat(),
                            "event_date_range_end": journal.event_date_range.end.isoformat(),
                            "user_id": str(user_id),
                        }
                        if action == InboundSyncAction.CREATE_JOURNAL:
                            journal_data["content"] = journal.content
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
                            "timezone": calendar_info.timezone,
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
                            existing_link.journal_id
                            if existing_link
                            else deduped_journal_id
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
                            recurring_event_id=google_event.recurring_event_id,
                            external_identity=external_identity,
                        )
                        session.add(outbox_event)
                        metrics["events_processed"] += 1

                    except Exception as e:  # noqa: BLE001
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

    except Exception as e:  # noqa: BLE001
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


async def _stop_previous_watch_channel(
    session: Any,
    user_id: str | int,
    channel: ActiveCalendarChannel,
) -> None:
    """Stop one channel a calendar still has recorded, best effort.

    Replacing a channel does not depend on the old one being stopped — the new
    registration stands either way — so a failure here is logged and swallowed
    rather than failing the setup. That matters most when the channel's account
    has since been disconnected: the token lookup below raises, and swallowing
    it is what lets the calendar be re-registered under an account that still
    works instead of failing every sweep.

    The client is built inside the try for the same reason, and for the
    channel's **own** account, since another account's token cannot address it.

    Args:
        session: Database session used to load the account's credentials
        user_id: Owner of the calendar
        channel: The recorded channel to stop
    """
    # A channel past its expiry has already been discarded by Google, so
    # stopping it would only spend a round trip to be told it does not exist.
    expiration = channel.channel_expiration
    if expiration is not None and expiration <= datetime.now(UTC):
        logger.debug(
            "Previous calendar webhook channel already expired",
            channel_id=channel.channel_id,
            channel_expiration=expiration.isoformat(),
        )
        return

    try:
        client = _create_google_client(session, user_id, channel.google_account_email)
        await client.stop_channel(
            channel_id=channel.channel_id,
            resource_id=channel.channel_resource_id,
        )
        logger.info(
            "Stopped previous calendar webhook channel",
            channel_id=channel.channel_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to stop previous watch channel",
            channel_id=channel.channel_id,
            google_account_email=channel.google_account_email,
            error=str(e),
        )


# Statuses from ``events().watch()`` that no retry can change: a request Google
# will keep rejecting, or a calendar this account cannot see.
_PERMANENT_WATCH_STATUSES: frozenset[int] = frozenset({400, 404})


def _is_permanent_watch_failure(error: Exception) -> bool:
    """Return True when retrying the webhook setup cannot change the outcome.

    Covers the three answers that are settled: the account is no longer
    connected, Google refused access to the calendar (``is_permission_denied``
    keeps rate and quota limits out of this), and a request Google rejects
    outright. Everything else — 429, 5xx, a dropped connection, a database
    blip — may succeed on a retry.
    """
    if isinstance(error, GoogleAuthTokensNotFoundError):
        return True
    if isinstance(error, HttpError):
        return (
            is_permission_denied(error)
            or error.resp.status in _PERMANENT_WATCH_STATUSES
        )
    return False


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

            # Serialise concurrent setups for this calendar before reading the
            # channel we are about to replace. Held until this block commits,
            # so the Google stop/watch pair below cannot interleave with
            # another run's.
            conn = await session.connection()
            repo = CalendarWatchRepository(conn)
            await repo.lock_calendar(
                user_id=str(user_id),
                google_calendar_id=google_calendar_id,
            )

            # Stop every channel the calendar still has recorded, whichever
            # account holds it. Scoping this to our own account would miss one
            # registered under the user's other account and leave it live
            # alongside the new one; stopping only the newest would strand the
            # rest, since their metadata is cleared below and Google would keep
            # delivering on them until they expire.
            for existing in await repo.get_active_channels(
                str(user_id), google_calendar_id
            ):
                await _stop_previous_watch_channel(session, user_id, existing)

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

            # The table is keyed by (user, account, calendar), so registering
            # under a different account than before inserts a second row rather
            # than replacing the first. Clear the channel it still claims, or
            # the renewal sweep keeps finding a channel that is no longer live.
            await repo.clear_channels_for_other_accounts(
                str(user_id), google_calendar_id, google_account_email
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

    except (HttpError, GoogleAuthTokensNotFoundError) as e:
        # Report a refusal and let the job succeed; raise anything that might
        # work next time so ARQ spends its retry budget on it. Returning for
        # everything, as this did, meant a transient Google or database error
        # near a channel's expiry waited for the next six-hourly sweep instead
        # of being retried in seconds. Raising for everything would be worse:
        # a read-only calendar would burn the whole retry budget every sweep.
        # See "Handler Convention: Returning vs Raising" in
        # docs/architecture/integration-architecture.md.
        if not _is_permanent_watch_failure(e):
            raise
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


# How often the renewal cron sweeps for lapsing channels. Paired with the
# ``webhook_renewal_threshold_hours`` setting (48h by default), this leaves
# several sweeps of margin before any channel can actually expire.
WEBHOOK_RENEWAL_CRON_INTERVAL_HOURS = 6


def _renewal_job_id(calendar: CalendarWatchRenewal) -> str:
    """Build the deduplicating ARQ job id for one calendar's renewal.

    Keying the job by the calendar it renews makes a sweep idempotent: if a
    previous sweep's job for this calendar is still queued or running, ARQ
    refuses the duplicate rather than dispatching a second setup that would
    race the first.
    """
    return (
        "calendar-webhook-renewal:"
        f"{calendar.user_id}:"
        f"{calendar.google_account_email}:"
        f"{calendar.google_calendar_id}"
    )


async def renew_calendar_webhooks(ctx: dict[str, Any]) -> dict[str, Any]:
    """Re-register Google Calendar push channels before they expire.

    Watch channels live for ``watch_events``' TTL (7 days) and Google then
    forgets them, silently ending push-driven sync. This cron runs ahead of
    that deadline and enqueues one ``setup_calendar_webhook`` job per lapsing
    calendar, so a single failing calendar neither blocks the others nor loses
    ARQ's retry budget.

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory

    Returns:
        Dictionary with renewal summary (calendars_due, jobs_enqueued, errors)
    """
    if not settings.webhook_base_url:
        logger.debug(
            "webhook_base_url not configured, skipping calendar webhook renewal"
        )
        return {"status": "skipped", "reason": "webhook_base_url not configured"}

    threshold_hours = settings.webhook_renewal_threshold_hours
    deadline = datetime.now(UTC) + timedelta(hours=threshold_hours)

    logger.info(
        "Starting calendar webhook renewal",
        renewal_threshold_hours=threshold_hours,
    )

    session_factory = ctx["session_factory"]
    jobs_enqueued = 0
    jobs_skipped = 0
    errors: list[str] = []

    try:
        async with session_factory() as session:
            conn = await session.connection()
            repo = CalendarWatchRepository(conn)
            due = await repo.select_due_for_renewal(deadline)

        logger.info("Found calendars due for webhook renewal", calendars_due=len(due))

        for calendar in due:
            try:
                job = await ctx["redis"].enqueue_job(
                    "setup_calendar_webhook",
                    calendar.google_account_email,
                    calendar.user_id,
                    calendar.google_calendar_id,
                    _job_id=_renewal_job_id(calendar),
                    _queue_name=ARQ_QUEUE_NAME,
                )
                if job:
                    jobs_enqueued += 1
                    logger.info(
                        "Enqueued calendar webhook renewal job",
                        job_id=job.job_id,
                        google_calendar_id=calendar.google_calendar_id,
                        user_id=calendar.user_id,
                    )
                else:
                    # ARQ returns None only when a job with this id is already
                    # queued or running, which is the deduplication working:
                    # a previous sweep is still setting this calendar up.
                    jobs_skipped += 1
                    logger.debug(
                        "Calendar webhook renewal already in flight",
                        google_calendar_id=calendar.google_calendar_id,
                        user_id=calendar.user_id,
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
                logger.warning(
                    "Error enqueueing calendar webhook renewal job",
                    google_calendar_id=calendar.google_calendar_id,
                    user_id=calendar.user_id,
                    error=str(e),
                )

        logger.info(
            "Calendar webhook renewal complete",
            calendars_due=len(due),
            jobs_enqueued=jobs_enqueued,
            jobs_skipped=jobs_skipped,
            errors_count=len(errors),
        )

        return {
            "status": "success",
            "calendars_due": len(due),
            "jobs_enqueued": jobs_enqueued,
            "jobs_skipped": jobs_skipped,
            "errors": errors,
            "worker_id": settings.worker_id,
        }

    except Exception as e:  # noqa: BLE001
        logger.error(
            "Calendar webhook renewal failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "jobs_enqueued": jobs_enqueued,
            "errors": errors,
        }


# ARQ Worker Settings
class GoogleWorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    """ARQ worker configuration.

    Operational defaults (``keep_result``, ``max_tries`` baseline, retry backoff)
    come from :class:`core_shared.SharedARQWorkerSettings` and equal arq's own
    constructor defaults, so they apply unchanged. ``health_check_interval`` is the
    exception: arq's ``get_kwargs`` reads only this leaf class's attributes, so the
    inherited shared ``30`` is invisible to arq and it falls back to arq's default
    of ``3600`` (this worker does not redeclare it). Only the functions list,
    consumer wiring, and documented overrides live here.
    """

    # Task functions — process_journal_event and process_tag_event are now
    # consumed directly from the Redis Stream via GoogleWorkerStreamConsumer
    # and are no longer registered as ARQ tasks.
    functions = [
        sync_google_contacts,
        push_local_contacts_to_google,
        sync_calendar_events,
        setup_calendar_webhook,
        renew_calendar_webhooks,  # Wrapper for the webhook renewal cron
        periodic_sync_all_accounts,  # Wrapper for periodic cron syncs
    ]

    # Worker lifecycle (shared factory). Cast to arq's StartupShutdown Protocol:
    # the hooks accept ``ctx`` but the shared LifecycleHook alias is a plain
    # positional Callable, which the Protocol's named-parameter form rejects.
    on_startup: StartupShutdown = cast("StartupShutdown", _on_startup)
    on_shutdown: StartupShutdown = cast("StartupShutdown", _on_shutdown)

    # Redis settings (shared helper).
    redis_settings = redis_settings_from_url(settings.redis_url)

    # Queue name.
    queue_name = ARQ_QUEUE_NAME

    # Documented overrides:
    # - job_timeout=600 (10 min): Google contact/calendar syncs page through large
    #   accounts and need longer than the shared 5-minute default.
    # - max_jobs: follow the worker's configured concurrency budget.
    job_timeout = 600
    max_jobs = settings.max_concurrent_jobs

    # Periodic sync cron (shared helper; empty when periodic sync is disabled),
    # plus the calendar webhook renewal cron. Renewal is deliberately *not*
    # gated on enable_periodic_sync: push notifications are what keeps calendars
    # fresh when periodic sync is off, so that is exactly when a lapsed watch
    # channel hurts most. It runs at minute 30 to stay clear of the periodic
    # sync cron at minute 0.
    cron_jobs = generate_cron_jobs(
        periodic_sync_all_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    ) + generate_interval_cron(
        renew_calendar_webhooks,
        every_hours=WEBHOOK_RENEWAL_CRON_INTERVAL_HOURS,
        minute=30,
    )


if __name__ == "__main__":
    # Setup OpenTelemetry
    setup_telemetry(settings)

    # Run the worker
    logger.info("Starting Google Contacts ARQ worker", worker_id=settings.worker_id)
    run_worker(GoogleWorkerSettings)
