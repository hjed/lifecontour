"""Shared builders for the ``TaskReadService`` unit suites.

Three files exercise the read service over mocked ports — a journal's task
list, the upcoming window and the past-day resolutions — and each needs the
same two entities and the same five doubles. They had three copies of both,
which is how the duplication gate first noticed them.

What lives here is the part that is genuinely identical: the *entities* a
repository hands back, and the ports that hold no per-file data. The doubles
that differ per file stay in their own module — a `task_repo` seeded with a
window's tasks is not a `task_repo` seeded with a journal's, and pretending
otherwise would produce a fixture no file actually wanted.

The matching **fixtures** are in ``conftest.py`` beside this module, because a
fixture cannot be imported. That split is the one ``task_doubles.py`` already
draws for the write-side suites.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import Task, TaskStatus

from tests.unit.tasks.task_doubles import USER_ID

#: The journal a task arose in, when a test does not care which.
#:
#: Always well in the past across these suites, as a creating journal almost
#: always is, so it can never be mistaken for the due anchor the listings judge.
CREATED_IN_ID = 100

#: Far enough out that nothing lapses by accident; the lapse tests move a date
#: deliberately.
FAR_FUTURE = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)


def make_journal(
    journal_id: int,
    when: datetime.date | datetime.datetime = FAR_FUTURE,
    *,
    title: str = "Permit Meeting",
) -> Journal:
    """A persisted journal, as the repository hands it back.

    ``when`` takes either shape because the suites want different things from
    it: the listing tests pin an *instant* far from any boundary, while the
    window and resolution tests name a **date** and care which local day it
    falls on. A bare date is placed at 09:00 UTC — mid-morning, so a test that
    means to cross a day boundary has to say so.
    """
    start = (
        when
        if isinstance(when, datetime.datetime)
        else datetime.datetime.combine(when, datetime.time(9, 0), tzinfo=datetime.UTC)
    )
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


def make_task(
    task_id: int,
    *,
    due_journal_id: int,
    creating_journal_id: int = CREATED_IN_ID,
    status: TaskStatus = TaskStatus.NOT_DONE,
) -> Task:
    """A persisted task, as the repository hands it back."""
    return Task(
        id=task_id,
        user_id=USER_ID,
        text=f"task {task_id}",
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        status=status,
    )


def journal_repo_knowing(known: dict[int, Journal]) -> AsyncMock:
    """A journal repository double that knows exactly ``known`` and nothing else.

    ``find_by_ids_for_user`` is owner-scoped in production, and the way a
    surface learns a journal is not the caller's is that it comes back
    **absent** rather than raising — so the double filters rather than failing
    on an unknown id, which is what lets a test assert on an absence.

    The mapping is the only thing that differs between the three suites; the
    closure around it was the same eleven lines in each.
    """
    repo = AsyncMock()

    async def fetch(_user_id: str, journal_ids: list[int]) -> list[Journal]:
        return [known[journal_id] for journal_id in journal_ids if journal_id in known]

    repo.find_by_ids_for_user.side_effect = fetch
    return repo
