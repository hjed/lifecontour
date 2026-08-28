"""How a merge's four statements become one summary per task.

The assembly step is pure, and it is the only part of the re-point that can be
tested without concurrency. That matters here, because what these tests are about
*is* concurrency: the affected tasks are read before the four statements run, and
nothing holds a task row or a link row still in between. ``_lock_journals`` takes
``FOR UPDATE`` on the two **journals**, which stops a task being anchored to the
absorbed one mid-merge — but a concurrent `delete_task` removes a task row and a
concurrent `detach_intermediate_journal` removes a link row without touching
either journal, so neither waits for the merge.

The integration fixture is one savepoint-bound connection, so a second session
cannot see the journals involved and none of these races can be *staged* — the
same limitation ``_lock_journals``' docstring records for the cases it closes.
What can be tested is the rule the assembly applies to the statements' answers,
which is where both failures live:

- a task the statements did not report **must not** be summarised at all,
  because the summary is what publishes an event; and
- an anchor fact from the pre-read **must not** survive a statement that did not
  report that task, because the pre-read is a snapshot and the ``UPDATE`` is the
  fact.

Found by review on the pull request that added the re-point's events, and both
halves reproduce against the assembly as first written: the first raised
``ValueError`` — a merge failing on task rows, which the specification forbids
outright — and the second published a due-journal move for a task whose row had
already gone.
"""

import pytest
from core_shared.models.tasks import TaskJournalRepointing

from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
    _AffectedTask,
)

TASK_ID = 7
USER_ID = "test-user-123"


def affected(**roles: bool) -> _AffectedTask:
    """A pre-read row for the task, holding the named anchor roles."""
    return _AffectedTask(
        task_id=TASK_ID,
        user_id=USER_ID,
        creating_anchor_moved=roles.get("creating", False),
        due_anchor_moved=roles.get("due", False),
    )


def summarise(
    row: _AffectedTask,
    *,
    anchored: set[int] | None = None,
    collapsed: set[int] | None = None,
    moved: set[int] | None = None,
    dropped: set[int] | None = None,
) -> TaskJournalRepointing | None:
    """The assembly step over the four statements' reports, each defaulting empty."""
    return SqlTaskAnchorRepository._summarise(
        row,
        anchored=anchored or set(),
        collapsed=collapsed or set(),
        moved=moved or set(),
        dropped=dropped or set(),
    )


class TestOnlyWhatTheStatementsReportedIsSummarised:
    """The pre-read proposes; the statements dispose."""

    def test_a_task_no_statement_reported_is_not_summarised(self) -> None:
        """The concurrent-detach case, and it used to raise.

        A task whose only reference to the absorbed journal is an intermediate
        link appears in the pre-read with no anchor role. If that link is
        detached before the re-point runs, all four statements pass it over —
        and the summary would have described nothing. The value object refuses
        to describe nothing, so the merge failed with a ``ValueError``: a merge
        blocked by a task, which the specification says can never happen.

        Nothing moved for this task, so the honest answer is no summary and
        therefore no event.
        """
        assert summarise(affected()) is None

    def test_an_anchor_the_update_did_not_report_is_not_claimed(self) -> None:
        """The concurrent-delete case.

        The pre-read saw the task anchored to the absorbed journal; by the time
        the anchor ``UPDATE`` ran, the row was gone, so it matched nothing. The
        pre-read's flag is a snapshot and the ``UPDATE``'s ``RETURNING`` is the
        fact — and a summary trusting the snapshot publishes a due-journal move
        for a task that no longer exists, which lands in that task's history
        *after* its own deletion marker.
        """
        assert summarise(affected(creating=True, due=True)) is None

    def test_an_anchor_the_update_reported_is_kept(self) -> None:
        """The ordinary case, so the guard above cannot pass by refusing everything."""
        summary = summarise(affected(due=True), anchored={TASK_ID})

        assert summary == TaskJournalRepointing(
            task_id=TASK_ID, user_id=USER_ID, due_anchor_moved=True
        )

    def test_a_link_moves_without_the_task_being_anchored_at_all(self) -> None:
        """A task merely mentioned in the absorbed journal is not in ``anchored``.

        The anchor statement never matches it, so gating the *link* facts on
        that set as well would silently drop every mention-only task from the
        merge's history.
        """
        summary = summarise(affected(), moved={TASK_ID})

        assert summary == TaskJournalRepointing(
            task_id=TASK_ID,
            user_id=USER_ID,
            source_link_removed=True,
            target_link_added=True,
        )

    @pytest.mark.parametrize(
        ("reports", "expected"),
        [
            ({"collapsed": True}, {"source_link_removed": True}),
            (
                {"moved": True, "dropped": True},
                {"source_link_removed": True},
            ),
            (
                {"dropped": True},
                {"target_link_removed": True},
            ),
        ],
    )
    def test_the_link_outcomes_are_unchanged_by_the_anchor_gate(
        self, reports: dict[str, bool], expected: dict[str, bool]
    ) -> None:
        """The three link shapes still read as they did, with no anchor involved.

        Guards the fix against the easy over-correction: gating everything on
        ``anchored`` would make a merge that moved only links publish nothing.
        """
        sets = {name: {TASK_ID} for name in reports}
        summary = summarise(affected(), **sets)

        assert summary == TaskJournalRepointing(
            task_id=TASK_ID, user_id=USER_ID, **expected
        )
