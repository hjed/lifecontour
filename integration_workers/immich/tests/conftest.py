"""Top-level pytest configuration for the immich worker test suite.

Registers the shared worker unit-test fixtures (``core_shared.testing``) as a
pytest plugin so ``mock_redis``, ``worker_settings``, ``session_factory_mock``
and ``arq_ctx`` are available as test arguments. ``pytest_plugins`` is only
honoured in the top-level conftest, which is why it lives here. Per-worker
integration-specific fixtures live in ``tests/integration/conftest.py``.
"""

pytest_plugins = ["core_shared.testing"]
