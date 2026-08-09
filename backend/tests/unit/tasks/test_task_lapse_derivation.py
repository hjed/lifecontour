"""Unit tests for the lapsed rule.

A task is lapsed when it is still *not done* and either its due journal's date
has passed or that journal has been cancelled. The rule is pure — a status, a
date, a cancellation flag and today — because it is derived on every read and
never stored, so nothing it depends on may be a repository.

Every case here is a boundary. The rule only says something at its edges:
yesterday against today against tomorrow, the two causes separately and
together, and the two statuses that switch it off entirely. Dates are fixed
rather than relative to ``now`` so each of those edges is exercised the same way
on every run.

The timezone does not appear at this level by design. ``due_journal_date`` and
``today`` arrive already resolved in the user's zone, by
``app.core.journal.services.journal_date_resolver`` — the split that lets a
batch caller resolve the timezone once. The tests that prove the *right* zone
was used live with the service and the integration suite.
"""

import datetime

import pytest
from core_shared.models.tasks import LapseReason, TaskStatus, derive_lapse_reason

TODAY = datetime.date(2026, 8, 9)
YESTERDAY = datetime.date(2026, 8, 8)
TOMORROW = datetime.date(2026, 8, 10)


def lapse(
    status: TaskStatus,
    due_journal_date: datetime.date,
    *,
    cancelled: bool = False,
) -> LapseReason | None:
    """The rule, with today pinned so each call reads as its own case."""
    return derive_lapse_reason(
        status=status,
        due_journal_date=due_journal_date,
        due_journal_cancelled=cancelled,
        today=TODAY,
    )


@pytest.mark.unit
class TestDatePassed:
    """The first cause: the moment the commitment was for has gone by."""

    def test_a_not_done_task_whose_due_date_has_passed_is_lapsed(self) -> None:
        """Yesterday is past, so the task lapsed for that reason."""
        assert lapse(TaskStatus.NOT_DONE, YESTERDAY) == LapseReason.DATE_PASSED

    def test_a_task_due_today_is_not_lapsed(self) -> None:
        """Today has not passed.

        This is the mirror of the write-time rule: ``is_future_dated`` is
        *strictly* after today, so a journal dated today is neither future-dated
        nor passed. Were this boundary inclusive, every task created for a
        journal earlier the same day would read as lapsed the moment it was
        made — and the two rules would disagree about the same journal.
        """
        assert lapse(TaskStatus.NOT_DONE, TODAY) is None

    def test_a_task_due_tomorrow_is_not_lapsed(self) -> None:
        """The ordinary outstanding commitment."""
        assert lapse(TaskStatus.NOT_DONE, TOMORROW) is None


@pytest.mark.unit
class TestDueJournalCancelled:
    """The second cause: the moment itself was called off."""

    def test_a_not_done_task_whose_due_journal_is_cancelled_is_lapsed(self) -> None:
        """A cancelled due journal lapses the task even though its date is future.

        The specification's cancellation rule carries no date condition — "a
        not-done task whose due journal has been cancelled is treated as
        lapsed" — because the moment the commitment was pinned to is not going
        to happen, whenever it was scheduled for.
        """
        assert (
            lapse(TaskStatus.NOT_DONE, TOMORROW, cancelled=True)
            == LapseReason.DUE_JOURNAL_CANCELLED
        )

    def test_cancellation_is_reported_ahead_of_a_passed_date(self) -> None:
        """Both causes at once report the cancellation.

        The reason exists so a surface can word the two differently, and
        cancellation is the more specific and more actionable of the pair: the
        meeting was called off, rather than merely that time went by.
        """
        assert (
            lapse(TaskStatus.NOT_DONE, YESTERDAY, cancelled=True)
            == LapseReason.DUE_JOURNAL_CANCELLED
        )


@pytest.mark.unit
class TestDoneAndCancelledTasksNeverLapse:
    """Lapsing is a property of an outstanding commitment, and only that."""

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    def test_a_passed_due_date_does_not_lapse_a_finished_task(
        self, status: TaskStatus
    ) -> None:
        """A task the user finished is not reproached for the date going by."""
        assert lapse(status, YESTERDAY) is None

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    def test_a_cancelled_due_journal_does_not_lapse_a_finished_task(
        self, status: TaskStatus
    ) -> None:
        """Cancelling the journal afterwards does not reopen a settled task."""
        assert lapse(status, YESTERDAY, cancelled=True) is None

    def test_a_done_task_due_in_the_future_is_not_lapsed_either(self) -> None:
        """Stated so the two statuses are not only tested on the lapsing side."""
        assert lapse(TaskStatus.DONE, TOMORROW) is None


@pytest.mark.unit
class TestLapseReasonValues:
    """The wire values, which a surface and a stored payload both depend on."""

    def test_the_two_reasons_are_the_documented_strings(self) -> None:
        """Pinned because the reason travels to clients as this string.

        Compared through ``.value``: a ``StrEnum`` member *is* its string, so
        mypy reads the direct comparison as one that can never hold and rejects
        it, even though it would pass at runtime.
        """
        assert LapseReason.DATE_PASSED.value == "date_passed"
        assert LapseReason.DUE_JOURNAL_CANCELLED.value == "due_journal_cancelled"

    def test_there_are_exactly_two_reasons(self) -> None:
        """A third cause would need a surface decision, not a quiet addition."""
        assert set(LapseReason) == {
            LapseReason.DATE_PASSED,
            LapseReason.DUE_JOURNAL_CANCELLED,
        }
