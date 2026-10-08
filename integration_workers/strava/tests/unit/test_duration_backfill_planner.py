"""Unit tests for the planner of the elapsed-time duration backfill.

The planner decides, for each journal linked to Strava activities, what its
duration should become (total elapsed time) and which stored values prove the
duration is still the one the sync wrote — so anything else is a user's edit.
"""

from duration_backfill import (
    MAX_MIXED_LINKS,
    ActivityTimes,
    DurationCorrection,
    plan_corrections,
)


def _times(moving: int, elapsed: int) -> ActivityTimes:
    return ActivityTimes(moving_time=moving, elapsed_time=elapsed)


class TestPlanCorrections:
    def test_a_single_activity_expects_its_moving_time(self) -> None:
        corrections = plan_corrections(
            links={7: ["111"]},
            activities={"111": _times(moving=3000, elapsed=3600)},
        )

        assert corrections == [
            DurationCorrection(
                journal_id=7,
                expected_durations=(3000,),
                corrected_duration=3600,
                strava_activity_ids=("111",),
            )
        ]

    def test_a_merged_journal_sums_every_linked_activity(self) -> None:
        """An ADDITIVE merge sums durations and keeps every Strava link.

        Mixed sums cover a merge done after the fix shipped, where one side
        was re-synced with elapsed time and the other still held moving time.
        """
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=3000, elapsed=3600),
                "222": _times(moving=1200, elapsed=1500),
            },
        )

        assert len(corrections) == 1
        correction = corrections[0]
        assert correction.corrected_duration == 5100
        assert set(correction.expected_durations) == {4200, 4500, 4800}
        assert correction.strava_activity_ids == ("111", "222")

    def test_the_already_correct_total_is_never_expected(self) -> None:
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=3000, elapsed=3600),
                "222": _times(moving=1500, elapsed=1500),
            },
        )

        assert 5100 not in corrections[0].expected_durations
        assert set(corrections[0].expected_durations) == {4500}

    def test_an_activity_that_never_stopped_needs_no_correction(self) -> None:
        corrections = plan_corrections(
            links={7: ["111"]},
            activities={"111": _times(moving=3600, elapsed=3600)},
        )

        assert corrections == []

    def test_a_journal_with_an_activity_missing_from_strava_is_skipped(
        self,
    ) -> None:
        """Without every activity's moving time the synced value is unknown."""
        corrections = plan_corrections(
            links={7: ["111", "deleted"]},
            activities={"111": _times(moving=3000, elapsed=3600)},
        )

        assert corrections == []

    def test_journals_are_planned_independently(self) -> None:
        corrections = plan_corrections(
            links={7: ["111"], 8: ["deleted"], 9: ["222"]},
            activities={
                "111": _times(moving=3000, elapsed=3600),
                "222": _times(moving=1000, elapsed=1100),
            },
        )

        assert [c.journal_id for c in corrections] == [7, 9]

    def test_beyond_the_mix_cap_only_the_all_moving_total_is_expected(
        self,
    ) -> None:
        ids = [str(n) for n in range(MAX_MIXED_LINKS + 1)]
        corrections = plan_corrections(
            links={7: ids},
            activities={i: _times(moving=100, elapsed=150) for i in ids},
        )

        assert corrections[0].expected_durations == (100 * len(ids),)
        assert corrections[0].corrected_duration == 150 * len(ids)
