"""Integration tests for the Snipe-IT settings repository's webhook token."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.models.snipeit import (
    SnipeItSettings,
    SnipeItWebhookToken,
    generate_webhook_token,
)

pytestmark = pytest.mark.integration

USER_ID = "snipeit-token-user"


def _settings(base_url: str = "https://snipeit.example.com") -> SnipeItSettings:
    return SnipeItSettings(user_id=USER_ID, base_url=base_url, snipeit_user_id="7")


@pytest.fixture
def repository(async_connection: AsyncConnection) -> SqlSnipeItSettingsRepository:
    return SqlSnipeItSettingsRepository(async_connection)


async def test_save_stores_the_webhook_token_for_a_new_user(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    token = generate_webhook_token()

    await repository.save(_settings(), new_webhook_token=token)

    assert await repository.get_webhook_token(USER_ID) == token


async def test_save_keeps_the_existing_token_when_updating(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    original = generate_webhook_token()
    await repository.save(_settings(), new_webhook_token=original)

    saved = await repository.save(
        _settings("https://other.example.com"),
        new_webhook_token=generate_webhook_token(),
    )

    assert saved.base_url == "https://other.example.com"
    assert await repository.get_webhook_token(USER_ID) == original


async def test_get_webhook_token_is_none_without_settings(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    assert await repository.get_webhook_token(USER_ID) is None


async def test_get_user_id_by_webhook_token_finds_the_owner(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    token = generate_webhook_token()
    await repository.save(_settings(), new_webhook_token=token)

    assert await repository.get_user_id_by_webhook_token(token) == USER_ID


async def test_get_user_id_by_webhook_token_is_none_for_an_unknown_token(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    await repository.save(_settings(), new_webhook_token=generate_webhook_token())

    unknown = SnipeItWebhookToken("not-a-real-token")
    assert await repository.get_user_id_by_webhook_token(unknown) is None


async def test_set_webhook_token_replaces_the_token(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    old_token = generate_webhook_token()
    await repository.save(_settings(), new_webhook_token=old_token)
    new_token = generate_webhook_token()

    assert await repository.set_webhook_token(USER_ID, new_token) is True

    assert await repository.get_webhook_token(USER_ID) == new_token
    assert await repository.get_user_id_by_webhook_token(old_token) is None
    assert await repository.get_user_id_by_webhook_token(new_token) == USER_ID


async def test_set_webhook_token_is_false_without_settings(
    repository: SqlSnipeItSettingsRepository,
) -> None:
    assert (
        await repository.set_webhook_token(USER_ID, generate_webhook_token()) is False
    )
