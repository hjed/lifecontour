"""Pytest configuration for Snipe-IT worker integration tests.

The database session fixtures and migrations are shared across every worker and
live in ``core_shared.testing.integration``. They are imported here (not
registered via ``pytest_plugins``) so the autouse ``apply_migrations`` stays
scoped to this integration subtree. Only the
worker-specific environment preamble remains below.
"""

import os

from core_shared.testing.integration import (
    apply_migrations,
    async_connection,
    async_engine,
    db_session,
    get_async_database_url,
)

# Set required environment variables for worker settings before imports happen.
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = get_async_database_url()
if "ENCRYPTION_KEY" not in os.environ:
    os.environ["ENCRYPTION_KEY"] = "testkey"

__all__ = ["apply_migrations", "async_connection", "async_engine", "db_session"]
