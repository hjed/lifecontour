"""Unit tests for ``ImmichAlbumCreationService`` with mocked collaborators.

These verify the orchestration logic in isolation: ownership/guard checks,
the Immich request shapes, and the SyncMetadata + ExternalReference writes that
link a journal to its new album (and therefore mark it PHOTO_ALBUM).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.integrations.immich.album_creation_service import (
    AlbumAlreadyLinkedError,
    EmptyAlbumSelectionError,
    ImmichAlbumCreationService,
    ImmichNotConnectedError,
    JournalNotFoundError,
)

USER_ID = "user-1"
OTHER_USER = "user-2"
SERVER_URL = "https://immich.example.com"
API_KEY = "key"
CREDS = (SERVER_URL, API_KEY)


def _journal(
    journal_id: int = 7, user_id: str = USER_ID, title: str = "Trip"
) -> Journal:
    return Journal(
        id=journal_id,
        user_id=user_id,
        title=title,
        content="",
        event_date_range=EventDateRange(
            start=datetime(2026, 1, 15, 0, 0, tzinfo=UTC),
            end=datetime(2026, 1, 15, 23, 59, 59, tzinfo=UTC),
        ),
    )


def _build(
    *,
    journal: Journal | None = None,
    credentials: tuple[str | None, str | None] = CREDS,
    existing_links: list[dict[str, Any]] | None = None,
    create_album_response: dict[str, Any] | None = None,
    shared_link_response: dict[str, Any] | None = None,
) -> tuple[ImmichAlbumCreationService, SimpleNamespace]:
    """Build a service plus a namespace of its (untyped) mock collaborators."""
    journal = journal if journal is not None else _journal()

    token_service = MagicMock()
    token_service.get_credentials = AsyncMock(return_value=credentials)

    api_client = MagicMock()
    api_client.search_metadata = AsyncMock(
        return_value=[
            {
                "id": "asset-1",
                "originalFileName": "a.jpg",
                "takenAt": "2026-01-15T05:00:00+00:00",
            },
            {"id": "asset-2", "originalFileName": "b.jpg"},
        ]
    )
    api_client.create_album = AsyncMock(
        return_value=create_album_response
        or {"id": "album-1", "albumName": "Trip", "assetCount": 2}
    )
    api_client.create_shared_link = AsyncMock(
        return_value=shared_link_response or {"id": "link-1", "key": "sharekey"}
    )

    journal_repo = MagicMock()
    journal_repo.find_by_id = AsyncMock(return_value=journal)

    album_link_repo = MagicMock()
    album_link_repo.find_external_links = AsyncMock(return_value=existing_links or [])
    album_link_repo.upsert_link = AsyncMock()

    user_settings_repo = MagicMock()
    user_settings_repo.get_timezone = AsyncMock(return_value="UTC")

    connection = MagicMock()
    connection.execute = AsyncMock()  # journal-row FOR UPDATE lock

    service = ImmichAlbumCreationService(
        connection=connection,
        token_service=token_service,
        api_client=api_client,
        journal_repo=journal_repo,
        album_link_repo=album_link_repo,
        user_settings_repo=user_settings_repo,
    )
    mocks = SimpleNamespace(
        token_service=token_service,
        api_client=api_client,
        journal_repo=journal_repo,
        album_link_repo=album_link_repo,
        user_settings_repo=user_settings_repo,
    )
    return service, mocks


# --- search_photos ---------------------------------------------------------


@pytest.mark.asyncio
async def test_search_photos_maps_assets_with_proxy_thumbnail_urls() -> None:
    service, mocks = _build()

    photos = await service.search_photos(7, USER_ID)

    assert [p.asset_id for p in photos] == ["asset-1", "asset-2"]
    assert photos[0].thumbnail_url == (
        "/api/integrations/immich/assets/asset-1/thumbnail"
    )
    assert photos[0].original_file_name == "a.jpg"
    assert photos[0].taken_at == "2026-01-15T05:00:00+00:00"
    assert photos[1].taken_at is None

    # The search window is the full UTC day for this UTC journal.
    mocks.api_client.search_metadata.assert_awaited_once()
    kwargs = mocks.api_client.search_metadata.await_args.kwargs
    assert kwargs["taken_after"] == "2026-01-15T00:00:00+00:00"
    assert kwargs["taken_before"] == "2026-01-15T23:59:59.999999+00:00"


@pytest.mark.asyncio
async def test_search_photos_unknown_journal_raises_not_found() -> None:
    service, _ = _build(journal=None)
    # An unset journal means find_by_id returns None.
    service.journal_repo.find_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(JournalNotFoundError):
        await service.search_photos(7, USER_ID)


@pytest.mark.asyncio
async def test_search_photos_other_users_journal_raises_not_found() -> None:
    service, _ = _build(journal=_journal(user_id=OTHER_USER))

    with pytest.raises(JournalNotFoundError):
        await service.search_photos(7, USER_ID)


@pytest.mark.asyncio
async def test_search_photos_not_connected_raises() -> None:
    service, _ = _build(credentials=(None, None))

    with pytest.raises(ImmichNotConnectedError):
        await service.search_photos(7, USER_ID)


# --- create_album ----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_album_writes_sync_metadata_and_reference() -> None:
    service, mocks = _build()

    result = await service.create_album(
        7, USER_ID, asset_ids=["asset-1", "asset-2"], create_shared_link=False
    )

    assert result.album_id == "album-1"
    assert result.journal_id == 7
    assert result.shared_link_url is None

    mocks.api_client.create_album.assert_awaited_once()
    create_kwargs = mocks.api_client.create_album.await_args.kwargs
    assert create_kwargs["album_name"] == "Trip"
    assert create_kwargs["asset_ids"] == ["asset-1", "asset-2"]
    mocks.api_client.create_shared_link.assert_not_awaited()

    # upsert_link is the single writer of the album sync_metadata link.
    link_args = mocks.album_link_repo.upsert_link.await_args
    assert link_args.args[0] == 7
    assert link_args.args[1] == "album-1"
    reference_data = link_args.args[2]
    assert reference_data["album_id"] == "album-1"
    assert reference_data["album_url"] == f"{SERVER_URL}/albums/album-1"
    assert "shared_link_url" not in reference_data
    assert link_args.kwargs["version_hash"]
    assert link_args.kwargs["bump_anchor"] is True


@pytest.mark.asyncio
async def test_create_album_commits_link_writes_in_unit_of_work(monkeypatch) -> None:
    """The journal<->album link writes must run inside a unit of work.

    The created album lives in Immich, but the sync_metadata link row that ties
    it back to the journal is committed by the service layer. Without an
    enclosing unit of work that write is rolled back at request teardown (the
    commit-timing race in #945), so the album exists yet the journal is never
    linked. This pins the commit to the service so the bug can't reappear via a
    caller (HTTP controller) that forgets to open one.
    """
    service, mocks = _build()

    uow: dict[str, Any] = {"active": False, "connection": None}

    @asynccontextmanager
    async def spy_unit_of_work(connection):
        uow["active"] = True
        uow["connection"] = connection
        try:
            yield connection
        finally:
            uow["active"] = False

    monkeypatch.setattr(
        "app.core.integrations.immich.album_creation_service.unit_of_work",
        spy_unit_of_work,
    )

    async def require_uow(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        assert uow["active"], "link write must run inside unit_of_work"

    mocks.album_link_repo.upsert_link.side_effect = require_uow

    await service.create_album(
        7, USER_ID, asset_ids=["asset-1"], create_shared_link=False
    )

    mocks.album_link_repo.upsert_link.assert_awaited_once()
    assert uow["connection"] is service.connection


@pytest.mark.asyncio
async def test_create_album_with_shared_link_persists_url() -> None:
    service, mocks = _build()

    result = await service.create_album(
        7, USER_ID, asset_ids=["asset-1"], create_shared_link=True
    )

    assert result.shared_link_url == f"{SERVER_URL}/share/sharekey"
    mocks.api_client.create_shared_link.assert_awaited_once()
    reference_data = mocks.album_link_repo.upsert_link.await_args.args[2]
    assert reference_data["shared_link_url"] == f"{SERVER_URL}/share/sharekey"


@pytest.mark.asyncio
async def test_create_album_already_linked_raises_and_skips_immich() -> None:
    service, mocks = _build(
        existing_links=[{"album_id": "old", "shared_link_url": None}]
    )

    with pytest.raises(AlbumAlreadyLinkedError):
        await service.create_album(
            7, USER_ID, asset_ids=["asset-1"], create_shared_link=False
        )

    mocks.api_client.create_album.assert_not_awaited()
    mocks.album_link_repo.upsert_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_album_empty_asset_ids_raises_before_immich() -> None:
    service, mocks = _build()

    with pytest.raises(EmptyAlbumSelectionError):
        await service.create_album(7, USER_ID, asset_ids=[], create_shared_link=False)

    mocks.api_client.create_album.assert_not_awaited()
    mocks.album_link_repo.upsert_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_album_not_connected_raises() -> None:
    service, _ = _build(credentials=(None, None))

    with pytest.raises(ImmichNotConnectedError):
        await service.create_album(
            7, USER_ID, asset_ids=["asset-1"], create_shared_link=False
        )


@pytest.mark.asyncio
async def test_create_album_unknown_journal_raises_not_found() -> None:
    service, _ = _build()
    service.journal_repo.find_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(JournalNotFoundError):
        await service.create_album(
            7, USER_ID, asset_ids=["asset-1"], create_shared_link=False
        )
