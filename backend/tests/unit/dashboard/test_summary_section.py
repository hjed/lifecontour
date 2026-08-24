"""Unit tests for the dashboard's summary section.

The whole of this phase is one decision table — which of the five
``SummaryStatus`` values the user's row can hold produces a section the page can
render, and which produce the quiet "no summary today" line — so it is tested as
a table, one row per assertion, off a pure function that takes the entity and
returns the payload or ``None``.

Two rules are worth stating because a reader could reasonably expect otherwise:

- **The dashboard never generates.** These tests take a summary row and map it;
  nothing here asks for one to be produced. That is the specification's
  read-only ruling, and the service test pins the repository call that follows
  from it.
- **A row that exists is not automatically showable.** ``FAILED`` and
  ``DISABLED`` are rows, and both map to *nothing to show* — the wireframe's W9
  — because a failed generation and a day below the two-journal threshold are
  both days the user has no summary for.
"""

import datetime

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary

from app.core.dashboard.models.sections import DashboardSummaryState
from app.core.dashboard.services.summary_section import _SHOWABLE, summary_section_for

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
TODAY = datetime.date(2026, 7, 31)

# The states that produce a payload, and the state each maps to. Kept beside the
# unshowable statuses below so the two lists can be checked against
# ``SummaryStatus`` as a whole — a sixth status added later belongs in one of
# them, and the exhaustiveness test fails until it is.
SHOWABLE = {
    SummaryStatus.GENERATED: DashboardSummaryState.GENERATED,
    SummaryStatus.PENDING: DashboardSummaryState.GENERATING,
    SummaryStatus.GENERATING: DashboardSummaryState.GENERATING,
}
UNSHOWABLE = (SummaryStatus.FAILED, SummaryStatus.DISABLED)


def summary(status: SummaryStatus, **overrides: object) -> JournalDailySummary:
    """A row in the given status, with counters and text worth asserting on."""
    fields: dict[str, object] = {
        "summary_text": "A long day of climbing and two good conversations.",
        "journal_count": 4,
        "event_count": 2,
        "contact_count": 3,
        "mood_average": 7.5,
    }
    fields.update(overrides)
    return JournalDailySummary(
        user_id=USER_ID,
        summary_date=TODAY,
        status=status,
        **fields,  # type: ignore[arg-type]
    )


class TestWhichStatusesTheDashboardCanShow:
    @pytest.mark.parametrize(("status", "expected"), list(SHOWABLE.items()))
    def test_a_showable_status_becomes_its_declared_state(
        self, status: SummaryStatus, expected: DashboardSummaryState
    ) -> None:
        section = summary_section_for(summary(status))

        assert section is not None
        assert section.state is expected

    @pytest.mark.parametrize("status", UNSHOWABLE)
    def test_an_unshowable_status_has_nothing_to_show(
        self, status: SummaryStatus
    ) -> None:
        """The section reports unavailable, which the page renders as W9's line."""
        assert summary_section_for(summary(status)) is None

    def test_no_row_at_all_has_nothing_to_show(self) -> None:
        """The state of a user whose AI is unconfigured: no row is ever written."""
        assert summary_section_for(None) is None

    def test_every_status_is_accounted_for(self) -> None:
        """A sixth status must be classified, not silently defaulted.

        Pinned against the module's own table as well as the enum, so the two
        lists above cannot drift into a private copy of the rules: a status added
        to production reaches ``SHOWABLE`` here, and one left out of production
        reaches ``UNSHOWABLE`` — where the test above then asserts it shows
        nothing. Without this line a new status could be waved through by
        editing the test alone.
        """
        assert SHOWABLE == _SHOWABLE
        assert set(SHOWABLE) | set(UNSHOWABLE) == set(SummaryStatus)


class TestTheStateVocabulary:
    def test_declares_exactly_the_two_states_a_payload_can_be_in(self) -> None:
        """The third of the wireframe's states is the envelope's *unavailable*.

        W33 declares three: generated, generating and unavailable. Two of them
        describe a summary that exists, so they live in the payload; the third
        describes its absence, so it is the section status and has no payload to
        sit in.
        """
        assert [state.value for state in DashboardSummaryState] == [
            "generated",
            "generating",
        ]


class TestTheKeyStatsFooter:
    def test_carries_the_four_counters_the_footer_renders(self) -> None:
        """W10's Journals / Events / Contacts / Avg Mood, straight off the row."""
        section = summary_section_for(summary(SummaryStatus.GENERATED))

        assert section is not None
        assert (
            section.journal_count,
            section.event_count,
            section.contact_count,
        ) == (4, 2, 3)

    def test_keeps_the_mood_average_out_of_ten(self) -> None:
        """W10 renders `7.5/10`, so the value must not arrive rescaled."""
        section = summary_section_for(summary(SummaryStatus.GENERATED))

        assert section is not None
        assert section.mood_average == 7.5

    def test_a_day_with_no_moods_recorded_has_no_average(self) -> None:
        """None, not zero — nobody had a mood of zero out of ten."""
        section = summary_section_for(
            summary(SummaryStatus.GENERATED, mood_average=None)
        )

        assert section is not None
        assert section.mood_average is None

    def test_the_counters_are_carried_while_generating_too(self) -> None:
        """The renderer decides where they show (W10 says generated only).

        Suppressing them here would make the payload's shape depend on state,
        which is a rendering rule leaking into the contract.
        """
        section = summary_section_for(summary(SummaryStatus.GENERATING))

        assert section is not None
        assert section.journal_count == 4


class TestTheSummaryText:
    def test_is_the_prose_the_generated_state_renders(self) -> None:
        section = summary_section_for(summary(SummaryStatus.GENERATED))

        assert section is not None
        assert section.summary_text == (
            "A long day of climbing and two good conversations."
        )

    @pytest.mark.parametrize(
        "status", [SummaryStatus.PENDING, SummaryStatus.GENERATING]
    )
    def test_is_withheld_until_the_summary_is_generated(
        self, status: SummaryStatus
    ) -> None:
        """A row invalidated after the day changed still holds yesterday's prose.

        ``get_display_text`` is what the journals view uses to keep that text off
        the screen, and reusing it is what makes "the same entity the journals
        view shows" true rather than approximately true.
        """
        section = summary_section_for(summary(status))

        assert section is not None
        assert section.summary_text is None
