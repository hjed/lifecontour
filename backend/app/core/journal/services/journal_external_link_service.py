"""The links from a journal to the records it mirrors in external systems.

A journal can be linked to Strava activities, Google Calendar events, Snipe-IT
maintenance records and assets, and Immich albums. The repository reads each of
those stores; this service gathers them into the display links an assistant is
shown alongside a journal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.integrations.external_link_helpers import (
    ExternalLinkInfo,
    build_journal_external_links,
)

if TYPE_CHECKING:
    from app.core.journal.models.repositories import JournalRepository
    from app.infrastructure.auth.immich_token_service import ImmichTokenService


def _is_google_calendar_event_link(event_link: dict[str, Any]) -> bool:
    """Whether an event link names a Google event on a Google-synced calendar.

    A link with a blank event id, or on a calendar that has no Google calendar id,
    cannot be opened in Google Calendar, so it is not an external link.
    """
    event_id = event_link.get("external_event_id")
    return (
        event_id is not None
        and event_id.strip(" ") != ""
        and event_link.get("calendar_id") is not None
    )


class JournalExternalLinkService:
    """Reads the external-system links for a journal."""

    def __init__(
        self,
        journal_repo: JournalRepository,
        immich_token_service: ImmichTokenService,
    ) -> None:
        self.journal_repo = journal_repo
        self.immich_token_service = immich_token_service

    async def links_for_journal(
        self, journal_id: int, user_id: str
    ) -> list[ExternalLinkInfo]:
        """Every external link for the journal, as the user's integrations see it.

        ``user_id`` scopes the Snipe-IT links and supplies the user's Immich
        server URL (read without decrypting the API key).
        """
        # Every Strava activity linked to the journal — an additively merged
        # journal carries more than one.
        strava_activity_ids = await self.journal_repo.get_strava_activity_ids(
            journal_id
        )
        snipeit_links = await self.journal_repo.get_snipeit_links(journal_id, user_id)
        immich_album_links = await self.journal_repo.get_immich_album_links(journal_id)
        immich_server_url = await self.immich_token_service.get_server_url(user_id)
        external_event_links = [
            event_link
            for event_link in await self.journal_repo.get_external_event_links(
                journal_id
            )
            if _is_google_calendar_event_link(event_link)
        ]

        return build_journal_external_links(
            strava_activity_ids=strava_activity_ids,
            external_event_links=external_event_links,
            snipeit_links=snipeit_links,
            immich_album_links=immich_album_links,
            immich_server_url=immich_server_url,
        )
