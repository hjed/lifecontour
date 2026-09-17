"""Migration test for 0114 (per-user Snipe-IT webhook token).

Verifies that upgrading ``0113 -> 0114`` gives every existing Snipe-IT settings
row its own URL-safe webhook token, that the column then rejects missing and
duplicate tokens, and that the downgrade drops it again.

Runs against an isolated throwaway database so the shared session DB is untouched.
"""

import re
from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import columns

_URL_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


async def _seed_settings(engine_url: str, user_ids: list[str]) -> None:
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            for user_id in user_ids:
                await conn.execute(
                    text(
                        "INSERT INTO snipeit_settings (user_id, base_url) "
                        "VALUES (:user_id, 'https://snipeit.example.com')"
                    ),
                    {"user_id": user_id},
                )
    finally:
        await engine.dispose()


async def _tokens_by_user(engine_url: str) -> dict[str, str | None]:
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT user_id, webhook_token FROM snipeit_settings")
                )
            ).fetchall()
            return {str(row.user_id): row.webhook_token for row in rows}
    finally:
        await engine.dispose()


async def _insert_raises_integrity_error(engine_url: str, statement: str) -> bool:
    engine = create_async_engine(engine_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement))
    except IntegrityError:
        return True
    finally:
        await engine.dispose()
    return False


@pytest.mark.integration
@pytest.mark.slow
class TestAddSnipeItWebhookTokenMigration:
    """0114 backfills a distinct webhook token for each Snipe-IT user."""

    async def test_upgrade_backfills_distinct_tokens_and_constrains_them(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0113")
        await _seed_settings(url, ["user-a", "user-b"])

        run_alembic(url, "upgrade", "0114")
        tokens = await _tokens_by_user(url)

        assert set(tokens) == {"user-a", "user-b"}
        assert all(
            token is not None and _URL_SAFE_TOKEN.match(token)
            for token in tokens.values()
        )
        assert tokens["user-a"] != tokens["user-b"]

        assert await _insert_raises_integrity_error(
            url,
            "INSERT INTO snipeit_settings (user_id, base_url) "
            "VALUES ('user-c', 'https://snipeit.example.com')",
        )
        assert await _insert_raises_integrity_error(
            url,
            "INSERT INTO snipeit_settings (user_id, base_url, webhook_token) "
            f"VALUES ('user-c', 'https://snipeit.example.com', '{tokens['user-a']}')",
        )

        run_alembic(url, "downgrade", "0113")
        assert "webhook_token" not in await columns(url, "snipeit_settings")
