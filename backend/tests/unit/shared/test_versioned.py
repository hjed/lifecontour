"""Unit tests for ``Versioned``, a write result that carries its version."""

from datetime import UTC, datetime

from core_shared.etag import resource_etag

from app.shared.versioned import Versioned

VERSION = datetime(2026, 10, 18, 9, 30, tzinfo=UTC)


def test_etag_is_the_aggregate_tag_of_the_committed_version() -> None:
    written = Versioned(value=("old", "new"), updated_at=VERSION)

    assert written.etag("contacts", 7) == resource_etag("contacts", 7, VERSION)
