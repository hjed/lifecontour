"""Migration test for 0130 (force one full Google contacts sync).

Google sync now imports nicknames, but the processor skips a person whose etag
has not moved, so a contact Google has not changed would never receive its
nickname. 0130 clears every account's contacts sync token: the next smart sync
is then a full sync, whose events are applied whatever their etag. Nothing else
- the calendar side, the auth rows, the sync links and their etags (which the
push still sends for concurrency) - is touched.
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import RunAlembic

_PREVIOUS_REVISION = "0129"
_REVISION = "0130"


async def _execute(url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    """Run ``sql`` in its own transaction; return its rows when it returns any."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.all() if result.returns_rows else None
    finally:
        await engine.dispose()


@pytest.mark.integration
class TestForceFullGoogleContactsSyncMigration:
    @pytest.mark.asyncio
    async def test_clears_contacts_sync_tokens_only(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        await _execute(
            url,
            """
            INSERT INTO user_google_integration
                (user_id, google_account_email, contacts_sync_token,
                 created_at, updated_at)
            VALUES ('user-1', 'a@example.com', 'token-a', now(), now()),
                   ('user-2', 'b@example.com', NULL, now(), now())
            """,
        )
        await _execute(
            url,
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 last_synced_at, version_hash, sync_status,
                 internal_entity_type, external_entity_type)
            VALUES ('user-1', 1, 'google', 'people/c1', now(), 'etag-1',
                    'success', 'contact', 'person')
            """,
        )

        run_alembic(url, "upgrade", _REVISION)

        tokens = await _execute(
            url,
            "SELECT google_account_email, contacts_sync_token "
            "FROM user_google_integration ORDER BY google_account_email",
        )
        assert [tuple(row) for row in tokens] == [
            ("a@example.com", None),
            ("b@example.com", None),
        ]
        etags = await _execute(url, "SELECT version_hash FROM sync_metadata")
        assert [tuple(row) for row in etags] == [("etag-1",)]

    @pytest.mark.asyncio
    async def test_downgrade_is_a_no_op(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _REVISION)

        run_alembic(url, "downgrade", _PREVIOUS_REVISION)
