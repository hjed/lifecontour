"""Unit tests for the planner of the elapsed-time duration backfill.

The planner decides, for each journal linked to Strava activities, what its
duration should become (total elapsed time) and which stored values prove the
duration is still the one the sync wrote — so anything else is a user's edit.
"""

from duration_backfill import (
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
        """An ADDITIVE merge sums durations and keeps every Strava link."""
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=3000, elapsed=3600),
                "222": _times(moving=1200, elapsed=1500),
            },
        )

        assert corrections[0] == DurationCorrection(
            journal_id=7,
            expected_durations=(4200,),
            corrected_duration=5100,
            strava_activity_ids=("111", "222"),
        )

    def test_a_merged_journal_overwritten_by_one_activity_is_corrected_to_it(
        self,
    ) -> None:
        """A webhook update of one merged activity re-saved its moving time alone.

        The sync now writes that activity's elapsed time, so that is the
        correction — one per linked activity, each its own compare-and-set.
        """
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=3000, elapsed=3600),
                "222": _times(moving=1200, elapsed=1500),
            },
        )

        assert corrections[1:] == [
            DurationCorrection(
                journal_id=7,
                expected_durations=(3000,),
                corrected_duration=3600,
                strava_activity_ids=("111",),
            ),
            DurationCorrection(
                journal_id=7,
                expected_durations=(1200,),
                corrected_duration=1500,
                strava_activity_ids=("222",),
            ),
        ]

    def test_a_merged_duration_with_a_manual_part_matches_nothing(self) -> None:
        """Two activities (100/200 each) merged with a manual 100: stored 300.

        Only values the sync itself wrote are expected, so the manual part is
        never folded into a correction.
        """
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=100, elapsed=200),
                "222": _times(moving=100, elapsed=200),
            },
        )

        assert all(300 not in c.expected_durations for c in corrections)

    def test_identical_activity_corrections_are_not_repeated(self) -> None:
        corrections = plan_corrections(
            links={7: ["111", "222"]},
            activities={
                "111": _times(moving=100, elapsed=200),
                "222": _times(moving=100, elapsed=200),
            },
        )

        assert [(c.expected_durations, c.corrected_duration) for c in corrections] == [
            ((200,), 400),
            ((100,), 200),
        ]

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
