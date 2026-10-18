"""
Pytest configuration for the backend unit tests.

CI's backend unit job selects tests with ``pytest -m unit``, so a test without
the ``unit`` marker never runs there. Every test under this directory is marked
automatically; an explicit ``pytestmark = pytest.mark.unit`` is not needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

UNIT_TESTS_DIR = Path(__file__).parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under ``tests/unit`` as ``unit`` before ``-m`` deselects.

    The hook receives every collected item, not only this directory's, so it
    filters on path. ``tryfirst`` runs it ahead of pytest's marker deselection.
    """
    for item in items:
        if item.path.is_relative_to(UNIT_TESTS_DIR):
            item.add_marker(pytest.mark.unit)
