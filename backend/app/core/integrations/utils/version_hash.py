"""
Utility functions for calculating version hashes for idempotency checks.

Version hashes are used to detect changes in external data and implement
idempotent sync operations.
"""

import hashlib
import json
from typing import Any


def calculate_version_hash(data: dict[str, Any]) -> str:
    """
    Calculate a SHA-256 hash of the data for change detection.

    This hash is used to implement idempotency - if the hash matches
    the stored version_hash in SyncMetadata, we know the data hasn't
    changed and can skip the sync operation.

    Args:
        data: Dictionary of data to hash (typically from external API)

    Returns:
        SHA-256 hash as hex string (64 characters)

    Example:
        >>> data = {"name": "John Doe", "email": "john@example.com"}
        >>> hash1 = calculate_version_hash(data)
        >>> hash2 = calculate_version_hash(data)
        >>> hash1 == hash2
        True
        >>> data["email"] = "jane@example.com"
        >>> hash3 = calculate_version_hash(data)
        >>> hash1 == hash3
        False
    """
    # Sort keys for consistent hashing
    json_str = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def calculate_contact_version_hash(contact_data: dict[str, Any]) -> str:
    """
    Calculate version hash specifically for contact data.

    This extracts the relevant fields from the internal Contact dict
    representation and calculates a hash. Internal fields like id,
    contact_id, created_at, updated_at are excluded.

    Args:
        contact_data: Contact data dict (internal format from serialize_contact)

    Returns:
        SHA-256 hash as hex string

    Example:
        >>> contact = {
        ...     "first_name": "John",
        ...     "last_name": "Doe",
        ...     "methods": [{"method_type": "email", "value": "john@example.com"}],
        ... }
        >>> hash_value = calculate_contact_version_hash(contact)
        >>> len(hash_value)
        64
    """
    # Extract fields that matter for change detection
    relevant_fields = {
        "first_name": contact_data.get("first_name"),
        "last_name": contact_data.get("last_name"),
        "middle_name": contact_data.get("middle_name"),
        "nick_name": contact_data.get("nick_name"),
        "company": contact_data.get("company"),
        "job_title": contact_data.get("job_title"),
        "is_favourite": contact_data.get("is_favourite", False),
        "methods": contact_data.get("methods", []),
        "addresses": contact_data.get("addresses", []),
        "notes": contact_data.get("notes", []),
        "tags": contact_data.get("tags", []),
        "important_dates": contact_data.get("important_dates", []),
    }

    return calculate_version_hash(relevant_fields)
