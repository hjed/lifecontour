"""Top-level pytest configuration for the snipeit worker test suite.

Registers the shared worker unit-test fixtures (``core_shared.testing``) as a
pytest plugin so ``mock_redis``, ``worker_settings``, ``session_factory_mock``
and ``arq_ctx`` are available as test arguments. ``pytest_plugins`` is only
honoured in the top-level conftest, which is why it lives here. Per-worker
integration-specific fixtures live in ``tests/integration/conftest.py``.
"""

pytest_plugins = ["core_shared.testing"]

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _fresh_rate_limiters() -> Iterator[None]:
    """Give each test its own Snipe-IT rate limit budget.

    The worker shares one limiter per Snipe-IT instance for the life of the
    process; across a test session that budget would run out and fail
    unrelated tests.
    """
    from snipeit_rate_limiter import _shared_limiters

    _shared_limiters.clear()
    yield
    _shared_limiters.clear()
