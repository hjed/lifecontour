"""
Unit tests for external link URL construction helpers.

Tests URL construction for external system links displayed on
journal and contact detail pages. Covers Strava, Google Calendar,
and Google Contacts URL patterns.
"""

import base64

from app.core.integrations.external_link_helpers import (
    ExternalLinkInfo,
    build_contact_external_links,
    build_google_calendar_event_url,
    build_google_contacts_url,
    build_immich_album_url,
    build_immich_person_url,
    build_journal_external_links,
    build_strava_activity_url,
)


class TestStravaActivityUrl:
    """Tests for Strava activity URL construction."""

    def test_valid_activity_id_returns_url(self) -> None:
        """Valid Strava activity ID produces correct URL."""
        url = build_strava_activity_url("12345678")
        assert url == "https://www.strava.com/activities/12345678"

    def test_none_returns_none(self) -> None:
        """None activity ID returns None."""
        assert build_strava_activity_url(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string activity ID returns None."""
        assert build_strava_activity_url("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only activity ID returns None."""
        assert build_strava_activity_url("   ") is None

    def test_large_activity_id(self) -> None:
        """Large numeric activity ID is handled correctly."""
        url = build_strava_activity_url("99999999999")
        assert url == "https://www.strava.com/activities/99999999999"


class TestGoogleCalendarEventUrl:
    """Tests for Google Calendar event URL construction."""

    def test_valid_event_id_returns_url(self) -> None:
        """Valid event ID is base64-encoded in the URL."""
        event_id = "abc123event"
        url = build_google_calendar_event_url(event_id)

        expected_eid = base64.urlsafe_b64encode(event_id.encode()).decode().rstrip("=")
        assert url == f"https://calendar.google.com/calendar/event?eid={expected_eid}"

    def test_none_returns_none(self) -> None:
        """None event ID returns None."""
        assert build_google_calendar_event_url(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string event ID returns None."""
        assert build_google_calendar_event_url("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only event ID returns None."""
        assert build_google_calendar_event_url("   ") is None

    def test_special_characters_in_event_id(self) -> None:
        """Event ID with special characters is base64-encoded correctly."""
        event_id = "event+with/special=chars"
        url = build_google_calendar_event_url(event_id)

        expected_eid = base64.urlsafe_b64encode(event_id.encode()).decode().rstrip("=")
        assert url == f"https://calendar.google.com/calendar/event?eid={expected_eid}"

    def test_with_calendar_id(self) -> None:
        """Event ID and Calendar ID are concatenated and base64-encoded."""
        event_id = "abc123event"
        calendar_id = "test@group.calendar.google.com"
        url = build_google_calendar_event_url(event_id, calendar_id)

        expected_content = f"{event_id} {calendar_id}"
        expected_eid = (
            base64.urlsafe_b64encode(expected_content.encode()).decode().rstrip("=")
        )
        assert url == f"https://calendar.google.com/calendar/event?eid={expected_eid}"


class TestGoogleContactsUrl:
    """Tests for Google Contacts URL construction."""

    def test_valid_resource_name_returns_url(self) -> None:
        """Valid resource name produces correct URL."""
        url = build_google_contacts_url("c12345678")
        assert url == "https://contacts.google.com/person/c12345678"

    def test_none_returns_none(self) -> None:
        """None resource name returns None."""
        assert build_google_contacts_url(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string resource name returns None."""
        assert build_google_contacts_url("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only resource name returns None."""
        assert build_google_contacts_url("   ") is None

    def test_resource_name_with_people_prefix(self) -> None:
        """Resource name with 'people/' prefix strips the prefix."""
        url = build_google_contacts_url("people/c12345678")
        assert url == "https://contacts.google.com/person/c12345678"


class TestImmichPersonUrl:
    """Tests for Immich person URL construction."""

    def test_valid_inputs_return_url(self) -> None:
        """Valid server URL and person ID produce correct URL."""
        url = build_immich_person_url("https://immich.example.com", "person-uuid")
        assert url == "https://immich.example.com/people/person-uuid"

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slash on the server URL is removed."""
        url = build_immich_person_url("https://immich.example.com/", "person-uuid")
        assert url == "https://immich.example.com/people/person-uuid"

    def test_none_server_url_returns_none(self) -> None:
        """Missing server URL returns None."""
        assert build_immich_person_url(None, "person-uuid") is None

    def test_none_person_id_returns_none(self) -> None:
        """Missing person ID returns None."""
        assert build_immich_person_url("https://immich.example.com", None) is None

    def test_blank_inputs_return_none(self) -> None:
        """Whitespace-only inputs return None."""
        assert build_immich_person_url("   ", "person-uuid") is None
        assert build_immich_person_url("https://immich.example.com", "  ") is None


class TestImmichAlbumUrl:
    """Tests for Immich album URL construction."""

    def test_valid_inputs_return_url(self) -> None:
        """Valid server URL and album ID produce correct URL."""
        url = build_immich_album_url("https://immich.example.com", "album-uuid")
        assert url == "https://immich.example.com/albums/album-uuid"

    def test_trailing_slash_stripped(self) -> None:
        """Trailing slash on the server URL is removed."""
        url = build_immich_album_url("https://immich.example.com/", "album-uuid")
        assert url == "https://immich.example.com/albums/album-uuid"

    def test_none_server_url_returns_none(self) -> None:
        """Missing server URL returns None."""
        assert build_immich_album_url(None, "album-uuid") is None

    def test_none_album_id_returns_none(self) -> None:
        """Missing album ID returns None."""
        assert build_immich_album_url("https://immich.example.com", None) is None

    def test_blank_inputs_return_none(self) -> None:
        """Whitespace-only inputs return None."""
        assert build_immich_album_url("   ", "album-uuid") is None
        assert build_immich_album_url("https://immich.example.com", "  ") is None


class TestExternalLinkInfo:
    """Tests for ExternalLinkInfo dataclass."""

    def test_creation(self) -> None:
        """ExternalLinkInfo can be created with all fields."""
        link = ExternalLinkInfo(
            source="strava",
            url="https://www.strava.com/activities/123",
            external_id="123",
            unique_key="123",
        )
        assert link.source == "strava"
        assert link.url == "https://www.strava.com/activities/123"
        assert link.external_id == "123"
        assert link.unique_key == "123"

    def test_creation_with_none_url(self) -> None:
        """ExternalLinkInfo can be created with None URL."""
        link = ExternalLinkInfo(
            source="strava",
            url=None,
            external_id="123",
            unique_key="123",
        )
        assert link.url is None


class TestBuildJournalExternalLinks:
    """Tests for aggregating journal external links."""

    def test_no_links(self) -> None:
        """Journal with no external data produces empty list."""
        links = build_journal_external_links(
            external_event_links=[],
        )
        assert links == []

    def test_strava_only(self) -> None:
        """Journal with only Strava activity ID produces single Strava link."""
        links = build_journal_external_links(
            strava_activity_ids=["12345678"],
            external_event_links=[],
        )
        assert len(links) == 1
        assert links[0].source == "strava"
        assert links[0].external_id == "12345678"
        assert links[0].url == "https://www.strava.com/activities/12345678"

    def test_one_link_per_strava_activity(self) -> None:
        """An additively merged journal shows every activity it absorbed."""
        links = build_journal_external_links(
            strava_activity_ids=["111", "222"],
            external_event_links=[],
        )
        assert [link.external_id for link in links] == ["111", "222"]
        assert [link.url for link in links] == [
            "https://www.strava.com/activities/111",
            "https://www.strava.com/activities/222",
        ]

    def test_repeated_and_blank_strava_ids_are_ignored(self) -> None:
        """The same activity named twice is one link, and blanks are not links."""
        links = build_journal_external_links(
            strava_activity_ids=["111", " 111 ", "", "   "],
            external_event_links=[],
        )
        assert [link.external_id for link in links] == ["111"]

    def test_google_calendar_only(self) -> None:
        """Journal with only Google Calendar link produces single link."""
        links = build_journal_external_links(
            external_event_links=[
                {"external_event_id": "evt123", "calendar_id": "cal-uuid"}
            ],
        )
        assert len(links) == 1
        assert links[0].source == "google_calendar"
        assert links[0].external_id == "evt123"
        assert links[0].url is not None
        assert "calendar.google.com" in links[0].url

    def test_google_calendar_missing_event_id(self) -> None:
        """External event link without event ID shows icon without URL."""
        links = build_journal_external_links(
            external_event_links=[
                {"external_event_id": None, "calendar_id": "cal-uuid"}
            ],
        )
        assert len(links) == 1
        assert links[0].source == "google_calendar"
        assert links[0].url is None
        assert links[0].external_id == ""

    def test_both_strava_and_google(self) -> None:
        """Journal with both Strava and Google Calendar produces both links."""
        links = build_journal_external_links(
            strava_activity_ids=["99999"],
            external_event_links=[
                {"external_event_id": "evt456", "calendar_id": "cal-uuid"}
            ],
        )
        assert len(links) == 2
        sources = {link.source for link in links}
        assert sources == {"strava", "google_calendar"}

    def test_multiple_google_calendar_links(self) -> None:
        """Journal linked to multiple calendars produces multiple Google links."""
        links = build_journal_external_links(
            external_event_links=[
                {"external_event_id": "evt1", "calendar_id": "cal-1"},
                {"external_event_id": "evt2", "calendar_id": "cal-2"},
            ],
        )
        google_links = [link for link in links if link.source == "google_calendar"]
        assert len(google_links) == 2


class TestBuildJournalExternalLinksImmich:
    """Tests for Immich album links on journals."""

    def test_album_link_only(self) -> None:
        """Album with no shared link produces a single immich_album link."""
        links = build_journal_external_links(
            external_event_links=[],
            immich_album_links=[{"album_id": "album-uuid", "shared_link_url": None}],
            immich_server_url="https://immich.example.com",
        )
        assert len(links) == 1
        assert links[0].source == "immich_album"
        assert links[0].external_id == "album-uuid"
        assert links[0].url == "https://immich.example.com/albums/album-uuid"
        assert links[0].unique_key == "album-album-uuid"

    def test_album_with_shared_link(self) -> None:
        """Album with a shared link produces both immich_album and immich_shared."""
        links = build_journal_external_links(
            external_event_links=[],
            immich_album_links=[
                {
                    "album_id": "album-uuid",
                    "shared_link_url": "https://immich.example.com/share/tok",
                }
            ],
            immich_server_url="https://immich.example.com",
        )
        by_source = {link.source: link for link in links}
        assert set(by_source) == {"immich_album", "immich_shared"}
        assert by_source["immich_album"].url == (
            "https://immich.example.com/albums/album-uuid"
        )
        shared = by_source["immich_shared"]
        assert shared.url == "https://immich.example.com/share/tok"
        assert shared.external_id == "album-uuid"
        assert shared.unique_key == "shared-album-uuid"

    def test_album_link_without_server_url_has_no_url(self) -> None:
        """Without a server URL the album link is icon-only (url None)."""
        links = build_journal_external_links(
            external_event_links=[],
            immich_album_links=[{"album_id": "album-uuid", "shared_link_url": None}],
            immich_server_url=None,
        )
        assert len(links) == 1
        assert links[0].source == "immich_album"
        assert links[0].url is None

    def test_album_alongside_strava(self) -> None:
        """Immich album link is aggregated with other source links."""
        links = build_journal_external_links(
            strava_activity_ids=["12345678"],
            external_event_links=[],
            immich_album_links=[{"album_id": "album-uuid", "shared_link_url": None}],
            immich_server_url="https://immich.example.com",
        )
        sources = {link.source for link in links}
        assert sources == {"strava", "immich_album"}

    def test_no_immich_links_when_omitted(self) -> None:
        """Omitting immich params keeps backward-compatible behaviour."""
        links = build_journal_external_links(
            external_event_links=[],
        )
        assert links == []


class TestBuildContactExternalLinks:
    """Tests for aggregating contact external links."""

    def test_no_references(self) -> None:
        """Contact with no external references produces empty list."""
        links = build_contact_external_links(external_references=[])
        assert links == []

    def test_google_contacts_link(self) -> None:
        """Contact with Google external reference produces Google Contacts link."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "google",
                    "external_entity_id": "c12345678",
                    "external_entity_type": "person",
                }
            ]
        )
        assert len(links) == 1
        assert links[0].source == "google_contacts"
        assert links[0].external_id == "c12345678"
        assert links[0].url == "https://contacts.google.com/person/c12345678"

    def test_strava_contact_link(self) -> None:
        """Contact with Strava external reference produces icon-only link."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "strava",
                    "external_entity_id": "athlete-123",
                    "external_entity_type": "athlete",
                }
            ]
        )
        assert len(links) == 1
        assert links[0].source == "strava"
        assert links[0].external_id == "athlete-123"
        # Strava athlete URL format TBC — icon only
        assert links[0].url is None

    def test_multiple_sources(self) -> None:
        """Contact with multiple external references produces multiple links."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "google",
                    "external_entity_id": "c111",
                    "external_entity_type": "person",
                },
                {
                    "external_system": "strava",
                    "external_entity_id": "athlete-222",
                    "external_entity_type": "athlete",
                },
            ]
        )
        assert len(links) == 2
        sources = {link.source for link in links}
        assert sources == {"google_contacts", "strava"}

    def test_unknown_system_ignored(self) -> None:
        """External reference from unknown system is still included."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "unknown_system",
                    "external_entity_id": "ext-id",
                    "external_entity_type": "entity",
                }
            ]
        )
        assert len(links) == 1
        assert links[0].source == "unknown_system"
        assert links[0].url is None

    def test_immich_person_link(self) -> None:
        """Immich person reference produces an immich link with a person URL."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "immich",
                    "external_entity_id": "person-uuid",
                    "external_entity_type": "person",
                }
            ],
            immich_server_url="https://immich.example.com",
        )
        assert len(links) == 1
        assert links[0].source == "immich"
        assert links[0].external_id == "person-uuid"
        assert links[0].url == "https://immich.example.com/people/person-uuid"

    def test_immich_person_link_without_server_url(self) -> None:
        """Without a server URL the immich person link is icon-only (url None)."""
        links = build_contact_external_links(
            external_references=[
                {
                    "external_system": "immich",
                    "external_entity_id": "person-uuid",
                    "external_entity_type": "person",
                }
            ],
        )
        assert len(links) == 1
        assert links[0].source == "immich"
        assert links[0].url is None
