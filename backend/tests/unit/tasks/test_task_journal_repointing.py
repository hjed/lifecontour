"""Unit tests for what a merge's re-point reports about one task.

``TaskJournalRepointing`` is the repository's answer to "what did this merge do
to this task?", and it is the only thing standing between four set-based SQL
statements and a user's history. Nothing downstream can recover a fact that
never reaches it: the event builds its whole payload from these five booleans.

So the two invariants asserted here are about *lies*, not about arithmetic. A
summary saying nothing moved describes a task the repository should never have
reported at all, and one saying the survivor's link was both gained and lost
describes a shape the four statements cannot produce.
"""

import dataclasses

import pytest
from core_shared.models.tasks import TaskJournalRepointing

TASK_ID = 7
USER_ID = "test-user-123"


def make(**facts: bool) -> TaskJournalRepointing:
    """A repointing over the shared identifiers, with the named facts set."""
    return TaskJournalRepointing(task_id=TASK_ID, user_id=USER_ID, **facts)


class TestARepointingRecordsSomething:
    """The repository only builds one of these for a task a merge touched."""

    @pytest.mark.parametrize(
        "fact",
        [
            "creating_anchor_moved",
            "due_anchor_moved",
            "source_link_removed",
            "target_link_added",
            "target_link_removed",
        ],
    )
    def test_each_fact_stands_on_its_own(self, fact: str) -> None:
        repointing = make(**{fact: True})

        assert getattr(repointing, fact) is True

    def test_a_repointing_that_moved_nothing_is_refused(self) -> None:
        """The failure this catches is silent, which is why it raises.

        Every task the repository reports references the absorbed journal in at
        least one of the three roles, so at least one of these is true. A summary
        with none of them set means an assembly step dropped the fact on the
        floor — and an event built from it would publish ``changed_fields: {}``,
        which projects zero rows and reads downstream exactly like a task the
        merge never touched.
        """
        with pytest.raises(ValueError, match="records no change"):
            make()

    def test_the_survivor_link_cannot_be_gained_and_lost_at_once(self) -> None:
        """A shape the four statements cannot produce, refused rather than rendered.

        A task only gains the survivor's link by having its own link re-pointed
        onto it, which requires it to have had none there before — and the
        redundancy cleanup only removes one that was already there. Both at once
        means the two ``RETURNING`` sets were read the wrong way round, and the
        history it would write says a journal was linked *and* unlinked by one
        merge.
        """
        with pytest.raises(ValueError, match="gained and lost"):
            make(target_link_added=True, target_link_removed=True)


class TestARepointingIsAFact:
    def test_it_cannot_be_edited_after_the_repository_reports_it(self) -> None:
        repointing = make(due_anchor_moved=True)

        with pytest.raises(dataclasses.FrozenInstanceError):
            repointing.due_anchor_moved = False  # type: ignore[misc]
