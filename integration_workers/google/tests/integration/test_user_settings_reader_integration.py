"""The worker reads the syncing user's default country from user_settings."""

import pytest
from core_shared.repositories import UserSettingsReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def test_no_settings_row_has_no_default_country(db_session: AsyncSession) -> None:
    assert await UserSettingsReader(db_session).get_default_country("nobody") is None


async def test_reads_the_users_own_default_country(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO user_settings (user_id, default_country)
            VALUES ('reader-1', 'NZ'), ('reader-2', 'GB')
            """
        )
    )

    reader = UserSettingsReader(db_session)

    assert await reader.get_default_country("reader-1") == "NZ"
    assert await reader.get_default_country("reader-2") == "GB"
