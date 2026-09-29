"""How a backend integration test creates a contact, and whose it is.

``seed_contact`` (and ``seed_contacts``, for bulk) is the one way to put a
contact row in the database from a test: ``tests/unit/test_contact_seeding_guard.py``
rejects raw inserts. The SQL lives in ``core_shared.testing.seeding`` so the
workers' tests share it.

``TEST_USER_ID`` is the acting user of every authenticated test client: the
``test_user`` fixture reads it, so a test that seeds rows for "the test user"
and the client that reads them cannot disagree.
"""

from typing import Final

from core_shared.testing.seeding import seed_contact, seed_contacts

TEST_USER_ID: Final = "test-user-123"

__all__ = ["TEST_USER_ID", "seed_contact", "seed_contacts"]
