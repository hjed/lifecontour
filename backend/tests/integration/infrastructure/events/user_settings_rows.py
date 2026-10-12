"""User settings rows for tests that resolve a background consumer's timezone."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.contact_seeding import OTHER_USER_ID

OTHER_USER_TIMEZONE = "Pacific/Auckland"


async def save_timezone(connection: AsyncConnection, user_id: str, zone: str) -> None:
    """Store ``zone`` as ``user_id``'s configured timezone."""
    await SqlUserSettingsRepository(connection).save(
        UserSettings(user_id=user_id, timezone=zone)
    )


async def save_newer_timezone_for_other_user(connection: AsyncConnection) -> None:
    """Give another user the most recently updated settings row.

    That row is what a "the" timezone lookup without a user would pick. Every
    row written in the test's one transaction shares ``NOW()``, so the row is
    dated a day later to make it the latest without depending on write order.
    """
    await save_timezone(connection, OTHER_USER_ID, OTHER_USER_TIMEZONE)
    await connection.execute(
        text(
            """
            UPDATE user_settings
            SET updated_at = NOW() + INTERVAL '1 day'
            WHERE user_id = :user_id
            """
        ),
        {"user_id": OTHER_USER_ID},
    )
