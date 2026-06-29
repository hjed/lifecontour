"""Shared worker test fixtures for integration-worker test suites.

This package is a **pytest plugin**: a worker (or ``core_shared``'s own) test
suite registers it by adding to its top-level ``conftest.py``::

    pytest_plugins = ["core_shared.testing"]

after which the fixtures defined here — ``mock_redis``, ``worker_settings``,
``session_factory_mock``, and ``arq_ctx`` — are available as test arguments. The
underlying ``make_*`` factory helpers are re-exported for direct import when a
test needs to build several instances or override values deeply.

The fixtures live once here instead of being re-implemented in every worker's
``conftest.py``. Per-worker ``conftest.py`` files keep only their
integration-specific fixtures (ITER14-005). This module is additive — workers
adopt it in a later phase — so importing it has no effect until a suite opts in
via ``pytest_plugins``.
"""

from __future__ import annotations

from core_shared.testing.fixtures import (
    DEFAULT_TEST_DATABASE_URL,
    arq_ctx,
    make_arq_ctx,
    make_mock_redis,
    make_session_factory_mock,
    make_worker_settings,
    mock_redis,
    session_factory_mock,
    worker_settings,
)

__all__ = [
    "DEFAULT_TEST_DATABASE_URL",
    # Factory helpers
    "make_arq_ctx",
    "make_mock_redis",
    "make_session_factory_mock",
    "make_worker_settings",
    # pytest fixtures
    "arq_ctx",
    "mock_redis",
    "session_factory_mock",
    "worker_settings",
]
