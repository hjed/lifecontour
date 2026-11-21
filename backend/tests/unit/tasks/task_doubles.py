"""Shared constants and entity builders for the task member-route unit tests.

``set_status``, ``update_task`` and ``delete_task`` all start from the same
position: one persisted task belonging to the acting user, reached through the
owner-scoped locking read, with the journal, contact and settings repositories
present but forbidden. Three files asserting that would otherwise carry three
copies of the same setup — the duplication Phase 5 recorded as a lesson and
Phase 6 acted on for the integration seeding.

The matching *fixtures* live in ``conftest.py`` beside this module; only the
plain values and builders are here, because a fixture cannot be imported.

``test_task_service_create.py`` keeps its own doubles rather than sharing these.
Creation loads journals and resolves contacts, so its repositories are
*configured* rather than merely forbidden, and folding the two together would
produce a fixture whose default no test actually wants.
"""

import datetime
from unittest.mock import AsyncMock

from core_shared.models.tasks import Task, TaskList, TaskStatus

from app.core.tasks.models.events import DomainEvent
from app.core.tasks.models.repositories import TaskListRepository

USER_ID = "test-user-123"
# A second, unrelated owner. Owner scoping is only worth asserting against a
# real acting user who is not the owner, never against a merely absent id.
OTHER_USER_ID = "other-user-456"

TASK_ID = 7
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22
# Where a retarget moves the task to, for the event tests.
# ``test_task_service_retarget.py`` and
# ``test_task_service_intermediate_journals.py`` each declare their own constant
# of the same name and value rather than importing this one — they predate this
# module and keep a self-contained constants block — so these are three literals
# that happen to agree, not one shared definition. Kept equal because reading the
# three files side by side is easier when the same journal has the same number;
# nothing breaks if they diverge, unlike ``UPDATED_TEXT``, which is genuinely
# shared because the event tests assert the pair the service tests produce.
NEW_DUE_JOURNAL_ID = 33
# A journal the task is merely *mentioned* in — neither anchor. The link events
# need a journal that holds no anchor role, because a payload built over
# ``DUE_JOURNAL_ID`` would read as correct while describing a link the service
# refuses to write.
INTERMEDIATE_JOURNAL_ID = 44
# The list a list task lives on. Its rows are never read by the unit tests: a
# read model carries the list id on the task and nothing about the list itself.
TASK_LIST_ID = 99

# The two journals a merge is between. Named rather than reusing the anchors
# because a merge is described from the *journals*' point of view — every link a
# task holds on the absorbed journal moves onto the survivor, whichever role it
# held — and a payload built over ``DUE_JOURNAL_ID`` would read as correct while
# describing only the one role that happens to match.
ABSORBED_JOURNAL_ID = 55
SURVIVING_JOURNAL_ID = 66

# The journal a delete removes. Its own id for the reason the merge's two are:
# a delete is described from the journal's side — every link a list task holds
# on it goes, whichever role it held.
DELETED_JOURNAL_ID = 88

# The people a task can reference. Two of them, because contact membership is
# carried as one ``changed_fields`` key *per contact* — ``contact:{id}`` — and a
# single id cannot show that two people produce two keys rather than overwriting
# each other under one shared field name.
CONTACT_ID = 3
OTHER_CONTACT_ID = 4

# The two people a merge is between. Named rather than reusing ``CONTACT_ID``
# and ``OTHER_CONTACT_ID`` for the reason the two journal ids above are: a merge
# is described from the *contacts*' point of view — the absorbed person's links
# move onto the survivor — and a payload built over the ids a task merely
# references would read as correct while describing the wrong pair.
ABSORBED_CONTACT_ID = 77
SURVIVING_CONTACT_ID = 88

ORIGINAL_TEXT = "return Sarah's book"
# What a reword moves it to. Shared rather than redeclared per file because the
# event tests assert the ``(old, new)`` pair the service tests produce, and two
# copies of "the new text" would let those two halves drift apart silently.
UPDATED_TEXT = "return Sarah's book and the DVD"


def make_task(
    status: TaskStatus = TaskStatus.NOT_DONE, *, text: str = ORIGINAL_TEXT
) -> Task:
    """A persisted task, as the repository would hand it back."""
    return Task(
        id=TASK_ID,
        user_id=USER_ID,
        text=text,
        creating_journal_id=CREATING_JOURNAL_ID,
        due_journal_id=DUE_JOURNAL_ID,
        status=status,
    )


def make_list_task(
    status: TaskStatus = TaskStatus.NOT_DONE,
    *,
    task_id: int = TASK_ID,
    creating_journal_id: int | None = None,
    due_journal_id: int | None = None,
    due_date: datetime.date | None = None,
) -> Task:
    """A persisted task on a list, holding whichever journals a case gives it.

    A list task may have no journal at all, only one of the two, or both, so
    every anchor defaults to absent and a case names the ones it wants.
    """
    return Task(
        id=task_id,
        user_id=USER_ID,
        text=ORIGINAL_TEXT,
        task_list_id=TASK_LIST_ID,
        position=0,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        due_date=due_date,
        status=status,
    )


def make_task_list_repo() -> AsyncMock:
    """A list repository whose every list is active.

    For the suites about journal-only tasks, which never reach it, and for any
    list task whose list being writable is not the point. Spec'd on the port, so
    a renamed method fails rather than being invented by the mock.
    """
    repo = AsyncMock(spec=TaskListRepository)
    repo.find_by_id_for_share.return_value = TaskList(
        id=TASK_LIST_ID, user_id=USER_ID, name="Packing", position=0
    )
    return repo


def published_events(publisher: AsyncMock) -> list[DomainEvent]:
    """Every event the service handed to its publisher, in order.

    Shared by the create and delete tests because both ask the same question of
    it — *what was published, and only that* — and both need the count as much
    as the contents: an operation that published twice would satisfy any
    assertion written as "a ``TaskCreated`` is among them".
    """
    return [call.args[0] for call in publisher.publish.await_args_list]
