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

    This extracts the relevant fields from Google Contacts API response
    and calculates a hash. Fields like metadata timestamps are excluded
    to avoid false positives.

    Args:
        contact_data: Contact data from Google Contacts API

    Returns:
        SHA-256 hash as hex string

    Example:
        >>> google_person = {
        ...     "resourceName": "people/c123",
        ...     "etag": "abc123",
        ...     "names": [{"givenName": "John", "familyName": "Doe"}],
        ...     "emailAddresses": [{"value": "john@example.com"}],
        ...     "metadata": {"updateTime": "2024-01-01T00:00:00Z"}  # Excluded
        ... }
        >>> hash_value = calculate_contact_version_hash(google_person)
        >>> len(hash_value)
        64
    """
    # Extract fields that matter for change detection
    # Exclude metadata timestamps and other fields that change without user action
    relevant_fields = {
        "names": contact_data.get("names", []),
        "emailAddresses": contact_data.get("emailAddresses", []),
        "phoneNumbers": contact_data.get("phoneNumbers", []),
        "addresses": contact_data.get("addresses", []),
        "organizations": contact_data.get("organizations", []),
        "biographies": contact_data.get("biographies", []),
        "birthdays": contact_data.get("birthdays", []),
        "urls": contact_data.get("urls", []),
        "relations": contact_data.get("relations", []),
        "nicknames": contact_data.get("nicknames", []),
        "photos": contact_data.get("photos", []),
        # Include etag if available (Google's version identifier)
        "etag": contact_data.get("etag"),
    }

    return calculate_version_hash(relevant_fields)
