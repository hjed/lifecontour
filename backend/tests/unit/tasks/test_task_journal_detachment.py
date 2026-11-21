"""Unit tests for what a journal delete reports about one list task.

``TaskJournalDetachment`` is the repository's answer to "what did deleting this
journal take from this task?". A list task does not block a journal delete; it
loses every link it held to the journal instead, and the event announcing that
loss is built from these three booleans alone. So, as with the merge's
``TaskJournalRepointing``, the invariant asserted here is about a lie: a
detachment that removed nothing describes a task the repository should never
have reported.
"""

import dataclasses

import pytest
from core_shared.models.tasks import TaskJournalDetachment

TASK_ID = 7
USER_ID = "test-user-123"


def make(**facts: bool) -> TaskJournalDetachment:
    """A detachment over the shared identifiers, with the named facts set."""
    return TaskJournalDetachment(task_id=TASK_ID, user_id=USER_ID, **facts)


class TestADetachmentRecordsSomething:
    @pytest.mark.parametrize(
        "fact", ["creating_anchor_removed", "due_anchor_removed", "link_removed"]
    )
    def test_each_fact_stands_on_its_own(self, fact: str) -> None:
        detachment = make(**{fact: True})

        assert getattr(detachment, fact) is True

    def test_all_three_can_be_true_at_once(self) -> None:
        """A list task created in, due in and once retargeted through one journal
        holds all three links on it, and loses all three together."""
        detachment = make(
            creating_anchor_removed=True, due_anchor_removed=True, link_removed=True
        )

        assert detachment.creating_anchor_removed
        assert detachment.due_anchor_removed
        assert detachment.link_removed

    def test_a_detachment_that_removed_nothing_is_refused(self) -> None:
        """Every task the repository reports referenced the deleted journal in
        at least one role. None set means a ``RETURNING`` set was misread, and
        the event built from it would publish an empty ``changed_fields`` that
        projects no history at all."""
        with pytest.raises(ValueError, match="records no change"):
            make()


class TestADetachmentIsAFact:
    def test_it_cannot_be_edited_after_the_repository_reports_it(self) -> None:
        detachment = make(due_anchor_removed=True)

        with pytest.raises(dataclasses.FrozenInstanceError):
            detachment.due_anchor_removed = False  # type: ignore[misc]

    def test_its_facts_are_keyword_only(self) -> None:
        """Three booleans in a row are exactly the arguments a caller swaps."""
        with pytest.raises(TypeError):
            TaskJournalDetachment(TASK_ID, USER_ID, True)  # type: ignore[call-arg]
