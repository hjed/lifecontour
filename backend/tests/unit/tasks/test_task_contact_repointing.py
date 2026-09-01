"""Unit tests for what a contact merge's re-point reports about one task.

``TaskContactRepointing`` is the repository's answer to "what did this merge do
to this task?", and — exactly as ``TaskJournalRepointing`` is for the journal
merge — it is the only thing standing between two set-based SQL statements and a
user's history. The event builds its whole payload from it.

The pair is *asymmetric*, which is the thing worth asserting. Every task the
repository reports lost its link to the absorbed contact, because that is what
being reported means; whether it *gained* one on the survivor depends on whether
it already had one. So the departure is implicit and the arrival is the field,
and the tests below are about the two directions never being confused: a
collapse that claimed an arrival would tell a user they were added to a task
they were already on.
"""

import dataclasses

import pytest
from core_shared.models.tasks import TaskContactRepointing

from app.core.tasks.models.events import contact_repointing_changed_fields
from tests.unit.tasks.task_doubles import (
    ABSORBED_CONTACT_ID,
    SURVIVING_CONTACT_ID,
    TASK_ID,
    USER_ID,
)


def make(*, survivor_link_added: bool, user_id: str = USER_ID) -> TaskContactRepointing:
    """A repointing over the shared identifiers."""
    return TaskContactRepointing(
        task_id=TASK_ID, user_id=user_id, survivor_link_added=survivor_link_added
    )


class TestARepointingCarriesItsOwner:
    """The merge reached this task through a contact and never read the row."""

    def test_the_owner_is_carried(self) -> None:
        assert make(survivor_link_added=True).user_id == USER_ID

    def test_a_repointing_with_no_owner_is_refused(self) -> None:
        """The one way this value object can lie, so it is the one it refuses.

        A task's owner has to travel on the event: a task-scoped history read
        resolves a hard-deleted task without a row to join back to. An empty
        owner reaches ``field_history`` as an empty string rather than as a
        failure, and nothing downstream can tell it from a task nobody owns.
        """
        with pytest.raises(ValueError, match="owner"):
            make(survivor_link_added=True, user_id="")


class TestARepointingIsAFact:
    def test_it_cannot_be_edited_after_the_repository_reports_it(self) -> None:
        repointing = make(survivor_link_added=True)

        with pytest.raises(dataclasses.FrozenInstanceError):
            repointing.survivor_link_added = False  # type: ignore[misc]


class TestTheChangedFieldsAMergeWrites:
    """The rule turning a re-point into the rows a history reader sees."""

    def test_a_moved_link_is_a_departure_and_an_arrival(self) -> None:
        """Two rows, because the key names the person.

        The absorbed contact leaves the task and the survivor arrives, and both
        halves have to be there: without the arrival the survivor's activity
        feed never gains the task, which is the whole point of re-pointing
        rather than dropping the link.
        """
        changed = contact_repointing_changed_fields(
            make(survivor_link_added=True),
            source_contact_id=ABSORBED_CONTACT_ID,
            survivor_contact_id=SURVIVING_CONTACT_ID,
        )

        assert changed == {
            f"contact:{ABSORBED_CONTACT_ID}": (ABSORBED_CONTACT_ID, None),
            f"contact:{SURVIVING_CONTACT_ID}": (None, SURVIVING_CONTACT_ID),
        }

    def test_a_collapsed_link_is_the_departure_alone(self) -> None:
        """The task already referenced the survivor, so it gained nothing.

        Announcing an arrival here would claim the merge added somebody to a
        task they were already on — a line in that person's own history for a
        thing that did not happen.
        """
        changed = contact_repointing_changed_fields(
            make(survivor_link_added=False),
            source_contact_id=ABSORBED_CONTACT_ID,
            survivor_contact_id=SURVIVING_CONTACT_ID,
        )

        assert changed == {
            f"contact:{ABSORBED_CONTACT_ID}": (ABSORBED_CONTACT_ID, None)
        }

    def test_the_pairs_are_old_then_new(self) -> None:
        """Positional, and nothing downstream can notice them being swapped.

        ``HistoryService._rows_from_changed_fields`` reads ``change[0]`` as the
        old value and never looks at the key, so a pair built the wrong way
        round renders the departure as an arrival in somebody's own history.
        """
        changed = contact_repointing_changed_fields(
            make(survivor_link_added=True),
            source_contact_id=ABSORBED_CONTACT_ID,
            survivor_contact_id=SURVIVING_CONTACT_ID,
        )

        departure = changed[f"contact:{ABSORBED_CONTACT_ID}"]
        arrival = changed[f"contact:{SURVIVING_CONTACT_ID}"]
        assert departure[0] == ABSORBED_CONTACT_ID and departure[1] is None
        assert arrival[0] is None and arrival[1] == SURVIVING_CONTACT_ID
