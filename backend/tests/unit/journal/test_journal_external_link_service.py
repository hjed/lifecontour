"""Unit tests for JournalExternalLinkService."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.integrations.external_link_helpers import ExternalLinkInfo
from app.core.journal.services.journal_external_link_service import (
    JournalExternalLinkService,
)


def _event_link(
    external_event_id: str | None,
    calendar_id: str | None,
    internal_calendar_id: str | None = "internal-cal",
) -> dict[str, Any]:
    return {
        "external_event_id": external_event_id,
        "calendar_id": calendar_id,
        "internal_calendar_id": internal_calendar_id,
    }


def _service(
    *,
    strava_activity_ids: list[str] | None = None,
    event_links: list[dict[str, Any]] | None = None,
    snipeit_links: list[dict[str, Any]] | None = None,
    immich_album_links: list[dict[str, Any]] | None = None,
    immich_server_url: str | None = None,
) -> tuple[JournalExternalLinkService, AsyncMock, AsyncMock]:
    journal_repo = AsyncMock()
    journal_repo.get_strava_activity_ids.return_value = strava_activity_ids or []
    journal_repo.get_external_event_links.return_value = event_links or []
    journal_repo.get_snipeit_links.return_value = snipeit_links or []
    journal_repo.get_immich_album_links.return_value = immich_album_links or []
    immich_token_service = AsyncMock()
    immich_token_service.get_server_url.return_value = immich_server_url
    service = JournalExternalLinkService(
        journal_repo=journal_repo, immich_token_service=immich_token_service
    )
    return service, journal_repo, immich_token_service


class TestLinksForJournal:
    @pytest.mark.asyncio
    async def test_google_links_need_an_event_id_and_a_google_calendar(self) -> None:
        service, _, _ = _service(
            event_links=[
                _event_link("event-1", "primary@google"),
                _event_link(None, "primary@google"),
                _event_link("   ", "primary@google"),
                _event_link("event-2", None),
            ]
        )

        links = await service.links_for_journal(7, "user-1")

        assert [(link.source, link.external_id) for link in links] == [
            ("google_calendar", "event-1")
        ]

    @pytest.mark.asyncio
    async def test_reads_every_source_for_the_journal_and_user(self) -> None:
        service, journal_repo, immich_token_service = _service(
            strava_activity_ids=["16152597201"],
            snipeit_links=[
                {
                    "integration_source": "snipeit",
                    "external_id": "42",
                    "base_url": "https://snipe.example",
                }
            ],
            immich_album_links=[{"album_id": "album-1", "shared_link_url": None}],
            immich_server_url="https://immich.example",
        )

        links = await service.links_for_journal(7, "user-1")

        assert links == [
            ExternalLinkInfo(
                source="strava",
                url="https://www.strava.com/activities/16152597201",
                external_id="16152597201",
                unique_key="16152597201",
            ),
            ExternalLinkInfo(
                source="snipeit",
                url="https://snipe.example/hardware/42",
                external_id="42",
                unique_key="asset-42",
            ),
            ExternalLinkInfo(
                source="immich_album",
                url="https://immich.example/albums/album-1",
                external_id="album-1",
                unique_key="album-album-1",
            ),
        ]
        journal_repo.get_strava_activity_ids.assert_awaited_once_with(7)
        journal_repo.get_external_event_links.assert_awaited_once_with(7)
        journal_repo.get_snipeit_links.assert_awaited_once_with(7, "user-1")
        journal_repo.get_immich_album_links.assert_awaited_once_with(7)
        immich_token_service.get_server_url.assert_awaited_once_with("user-1")
