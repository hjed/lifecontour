"""Pytest configuration for Google Contacts worker integration tests.

The database session fixtures and migrations are shared across every worker and
live in ``core_shared.testing.integration``. They are imported here (not
registered via ``pytest_plugins``) so the autouse ``apply_migrations`` stays
scoped to this integration subtree. The worker-settings
environment variables for this worker are set in ``tests/conftest.py``.
"""

from core_shared.testing.integration import (
    apply_migrations,
    async_connection,
    async_engine,
    db_session,
)

__all__ = ["apply_migrations", "async_connection", "async_engine", "db_session"]
