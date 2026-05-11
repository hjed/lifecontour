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

        expected_eid = base64.b64encode(event_id.encode()).decode()
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

        expected_eid = base64.b64encode(event_id.encode()).decode()
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


class TestExternalLinkInfo:
    """Tests for ExternalLinkInfo dataclass."""

    def test_creation(self) -> None:
        """ExternalLinkInfo can be created with all fields."""
        link = ExternalLinkInfo(
            source="strava",
            url="https://www.strava.com/activities/123",
            external_id="123",
        )
        assert link.source == "strava"
        assert link.url == "https://www.strava.com/activities/123"
        assert link.external_id == "123"

    def test_creation_with_none_url(self) -> None:
        """ExternalLinkInfo can be created with None URL."""
        link = ExternalLinkInfo(
            source="strava",
            url=None,
            external_id="123",
        )
        assert link.url is None


class TestBuildJournalExternalLinks:
    """Tests for aggregating journal external links."""

    def test_no_links(self) -> None:
        """Journal with no external data produces empty list."""
        links = build_journal_external_links(
            strava_activity_id=None,
            external_event_links=[],
        )
        assert links == []

    def test_strava_only(self) -> None:
        """Journal with only Strava activity ID produces single Strava link."""
        links = build_journal_external_links(
            strava_activity_id="12345678",
            external_event_links=[],
        )
        assert len(links) == 1
        assert links[0].source == "strava"
        assert links[0].external_id == "12345678"
        assert links[0].url == "https://www.strava.com/activities/12345678"

    def test_google_calendar_only(self) -> None:
        """Journal with only Google Calendar link produces single link."""
        links = build_journal_external_links(
            strava_activity_id=None,
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
            strava_activity_id=None,
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
            strava_activity_id="99999",
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
            strava_activity_id=None,
            external_event_links=[
                {"external_event_id": "evt1", "calendar_id": "cal-1"},
                {"external_event_id": "evt2", "calendar_id": "cal-2"},
            ],
        )
        google_links = [link for link in links if link.source == "google_calendar"]
        assert len(google_links) == 2


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
