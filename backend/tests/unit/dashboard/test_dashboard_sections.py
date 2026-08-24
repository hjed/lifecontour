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

import pytest

from app.core.dashboard.models.sections import (
    AgendaSectionData,
    DashboardSection,
    SectionStatus,
    TasksSectionData,
)

pytestmark = pytest.mark.unit


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


class TestTheStatusVocabulary:
    def test_renders_as_the_two_wire_values(self) -> None:
        """The strings are the contract the frontend narrows on (Phase 16)."""
        assert str(SectionStatus.READY) == "ready"
        assert str(SectionStatus.UNAVAILABLE) == "unavailable"
        assert [status.value for status in SectionStatus] == ["ready", "unavailable"]
