"""No test seeds a contact with its own SQL.

Every test that needs a contact row goes through ``seed_contact`` (in
``core_shared.testing.seeding``, re-exported by
``tests.integration.contact_seeding``), so a change to what a contact row
requires — its owner, first — lands in one statement rather than in every test
that happens to insert one.

The only other inserts allowed are the migration tests', which seed a schema
pinned at an older revision that the helper does not describe.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]

SCANNED_ROOTS = (
    REPO_ROOT / "backend" / "tests",
    REPO_ROOT / "core_shared",
    *sorted((REPO_ROOT / "integration_workers").glob("*/tests")),
)

ALLOWED = frozenset(
    {
        # The helper itself.
        "core_shared/core_shared/testing/seeding.py",
        # Migration tests seeding a schema at a pinned revision.
        "backend/tests/integration/contacts/test_add_user_id_to_contacts_migration.py",
        "backend/tests/integration/integrations/test_backfill_sync_metadata_migration.py",
        "backend/tests/integration/integrations/test_dedupe_bug_created_contacts_migration.py",
        "backend/tests/integration/integrations/test_drop_external_references_migration.py",
        "backend/tests/integration/mcp/test_reassign_synthetic_owner_migration.py",
    }
)

RAW_CONTACT_INSERT = re.compile(r"insert\s+into\s+(public\.)?contacts\b", re.IGNORECASE)


def _files_inserting_contacts() -> set[str]:
    found: set[str] = set()
    for root in SCANNED_ROOTS:
        for path in root.rglob("*.py"):
            if ".venv" in path.parts or path.resolve() == Path(__file__).resolve():
                continue
            if RAW_CONTACT_INSERT.search(path.read_text(encoding="utf-8")):
                found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_contacts_are_seeded_only_through_the_shared_helper() -> None:
    offenders = sorted(_files_inserting_contacts() - ALLOWED)

    assert offenders == [], (
        "Seed contacts with seed_contact (tests.integration.contact_seeding, or "
        "core_shared.testing.seeding in a worker) instead of raw SQL:\n"
        + "\n".join(offenders)
    )


def test_every_allowed_file_still_inserts_a_contact() -> None:
    """An entry that no longer needs the exemption is removed, not left to rot."""
    assert sorted(ALLOWED - _files_inserting_contacts()) == []
