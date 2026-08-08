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

from core_shared.models.tasks import Task, TaskStatus

USER_ID = "test-user-123"
# A second, unrelated owner. Owner scoping is only worth asserting against a
# real acting user who is not the owner, never against a merely absent id.
OTHER_USER_ID = "other-user-456"

TASK_ID = 7
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22

ORIGINAL_TEXT = "return Sarah's book"


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
