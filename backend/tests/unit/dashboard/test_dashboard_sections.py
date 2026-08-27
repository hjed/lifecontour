"""Unit tests for the dashboard section envelope.

Pins the distinction the dashboard's list sections rest on: one that read its
window and found nothing is **ready** with an empty payload, while one with no
payload at all is **unavailable**. Three later phases fill sections that must be
able to say which of the two happened, so the vocabulary is asserted here before
any of them depend on it.

Reporting unavailable is not a claim that something went wrong — the summary
section uses it for a day that simply has no summary. What the vocabulary
guarantees is narrower, and is what these tests hold: an empty payload and a
missing one are never the same value, so a caller cannot read "nothing scheduled
today" off a section that has not told it anything.
"""

import datetime

import pytest

from app.core.dashboard.models.sections import (
    AgendaEntry,
    AgendaParticipant,
    AgendaSectionData,
    AgendaTag,
    DashboardSection,
    SectionStatus,
    TasksSectionData,
)

pytestmark = pytest.mark.unit

NINE_AM = datetime.datetime(2026, 7, 31, 9, tzinfo=datetime.UTC)


class TestAReadySection:
    def test_keeps_the_payload_it_was_given(self) -> None:
        data = TasksSectionData()

        section = DashboardSection.ready(data)

        assert section.status is SectionStatus.READY
        assert section.data is data
        assert section.is_ready

    def test_an_empty_payload_is_still_ready(self) -> None:
        """Nothing due this week is an answer, not a failure to answer."""
        section = DashboardSection.ready(TasksSectionData())

        assert section.status is SectionStatus.READY
        assert section.data is not None


class TestAnUnavailableSection:
    def test_carries_no_data_at_all(self) -> None:
        """``data`` is null rather than an empty payload.

        A caller cannot then read an empty list off a section that never
        answered, and report "nothing scheduled today" on the strength of it.
        """
        section: DashboardSection[AgendaSectionData] = DashboardSection.unavailable()

        assert section.status is SectionStatus.UNAVAILABLE
        assert section.data is None
        assert not section.is_ready

    def test_is_not_the_same_as_an_empty_ready_section(self) -> None:
        empty = DashboardSection.ready(AgendaSectionData())
        unavailable: DashboardSection[AgendaSectionData] = (
            DashboardSection.unavailable()
        )

        assert empty != unavailable
        assert empty.status is not unavailable.status


class TestTheAgendaPayload:
    """The first section whose emptiness is a real answer rather than absence."""

    def test_a_day_with_nothing_on_it_carries_no_entries(self) -> None:
        assert AgendaSectionData().entries == ()

    def test_an_agenda_with_no_entries_is_ready_not_unavailable(self) -> None:
        """The distinction the wireframe's single empty line depends on.

        A page cannot say "nothing scheduled today" on the strength of a section
        that never answered, so an empty day has to be a payload rather than the
        absence of one.
        """
        section = DashboardSection.ready(AgendaSectionData())

        assert section.status is SectionStatus.READY
        assert section.data is not None
        assert section.data.entries == ()

    def test_an_entry_carries_what_the_card_renders(self) -> None:
        """Everything W12-W18 draws, and nothing pre-formatted for it."""
        tag = AgendaTag(id="t-1", name="social", color="#ff0000")
        entry = AgendaEntry(
            journal_id=42,
            title="Coffee with Sam",
            is_all_day=False,
            starts_at=NINE_AM,
            ends_at=NINE_AM + datetime.timedelta(hours=1),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            location="The good place",
            is_cancelled=False,
            tags=(tag,),
            participants=(AgendaParticipant(contact_id=7, name="Sam Taylor"),),
        )

        assert entry.tags == (tag,)
        assert entry.participants[0].name == "Sam Taylor"
        assert entry.location == "The good place"

    def test_an_entry_defaults_to_the_plainest_event_there_is(self) -> None:
        """Only the journal and its instants are required; the rest are absences."""
        entry = AgendaEntry(
            journal_id=1,
            title="A quiet event",
            is_all_day=True,
            starts_at=NINE_AM,
            ends_at=NINE_AM,
        )

        assert entry.start_time is None
        assert entry.end_time is None
        assert entry.location is None
        assert entry.is_cancelled is False
        assert entry.tags == ()
        assert entry.participants == ()


class TestTheStatusVocabulary:
    def test_renders_as_the_two_wire_values(self) -> None:
        """The strings are the contract the frontend narrows on (Phase 16)."""
        assert str(SectionStatus.READY) == "ready"
        assert str(SectionStatus.UNAVAILABLE) == "unavailable"
        assert [status.value for status in SectionStatus] == ["ready", "unavailable"]
