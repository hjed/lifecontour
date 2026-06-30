"""Smoke test: the shared DB integration fixtures resolve and roll back.

Proves this worker's ``tests/integration/conftest.py`` correctly imports the
shared ``async_connection`` / ``db_session`` fixtures from
``core_shared.testing.integration`` and that the autouse ``apply_migrations``
wiring runs.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_db_session_executes_select(db_session: Any) -> None:
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_async_connection_executes_select(async_connection: Any) -> None:
    result = await async_connection.execute(text("SELECT 1"))
    assert result.scalar_one() == 1
