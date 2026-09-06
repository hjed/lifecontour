"""Unit tests for the dashboard's tasks-section projection.

The section itself decides very little, and that is the point: which tasks are
in the window, in what order, and which are excluded were all settled by
``select_upcoming_tasks`` before this is reached, and are pinned against that
function in ``tests/unit/tasks/test_task_upcoming_window.py``. Re-asserting them
here through a projection that only iterates would test the loop.

What is genuinely this module's own, and is therefore asserted here:

- **``days_away``**, the material the W25 chip is drawn from. It is counted from
  the window's first day — which is the page's anchor — rather than left for a
  browser to derive, because subtracting dates in the browser's zone can land a
  day out near midnight in any zone away from the configured one.
- **The projection re-orders nothing and drops nothing.** A second sort here
  would be a copy of a rule that already has a home, and a cap would contradict
  the criterion that the whole window travels so a show-more costs no second
  request.
- **The window travels even when the answer is empty**, which is the one case a
  section cannot describe without it: "nothing due between today and next
  Sunday" needs a window no row can supply.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.tasks import (
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskReadModel,
    TaskStatus,
    UpcomingTasks,
    build_task_read_model,
    select_upcoming_tasks,
    upcoming_window,
)

from app.core.dashboard.services.tasks_section import tasks_section_for

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
TODAY = datetime.date(2026, 8, 11)
CREATING_JOURNAL_ID = 700


def make_model(
    task_id: int,
    *,
    due_date: datetime.date,
    text: str | None = None,
    title: str | None = None,
    status: TaskStatus = TaskStatus.NOT_DONE,
    contacts: list[TaskContactRef] | None = None,
) -> TaskReadModel:
    """A read model built the way the read service builds one.

    Through ``build_task_read_model`` rather than by hand, so the lapse verdict
    the projection carries through is the one production derives.
    """
    due_journal = TaskJournalRef(
        id=900 + task_id,
        title=title if title is not None else f"journal {task_id}",
        date=due_date,
        cancelled=False,
    )
    return build_task_read_model(
        task=Task(
            id=task_id,
            user_id=USER_ID,
            text=text if text is not None else f"task {task_id}",
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=due_journal.id,
            status=status,
        ),
        creating_journal=TaskJournalRef(
            id=CREATING_JOURNAL_ID,
            title="where it arose",
            date=TODAY - datetime.timedelta(days=30),
            cancelled=False,
        ),
        due_journal=due_journal,
        intermediate_journals=[],
        contacts=contacts if contacts is not None else [],
        today=TODAY,
    )


def selected(*models: TaskReadModel) -> UpcomingTasks:
    """The models as the read service hands them over: selected and ordered.

    The real selection rather than a hand-built ``UpcomingTasks``, so what the
    projection receives is what production gives it.
    """
    return select_upcoming_tasks(models, upcoming_window(TODAY))


class TestTheRowARowDraws:
    def test_it_carries_the_task_text_and_id(self) -> None:
        section = tasks_section_for(
            selected(make_model(12, due_date=TODAY, text="book the venue"))
        )

        (row,) = section.tasks
        assert row.task_id == 12
        assert row.text == "book the venue"

    def test_it_carries_the_due_journal_whole(self) -> None:
        """The W26 link needs an id and a title, and the chip needs the date."""
        section = tasks_section_for(
            selected(
                make_model(
                    12, due_date=datetime.date(2026, 8, 13), title="Monday standup"
                )
            )
        )

        (row,) = section.tasks
        assert row.due_journal.id == 912
        assert row.due_journal.title == "Monday standup"
        assert row.due_journal.date == datetime.date(2026, 8, 13)

    def test_it_carries_the_linked_contacts_in_link_order(self) -> None:
        """W27 draws a name per contact, and the order is the link order."""
        section = tasks_section_for(
            selected(
                make_model(
                    12,
                    due_date=TODAY,
                    contacts=[
                        TaskContactRef(id=5, display_name="Ada", photo_url="/a.png"),
                        TaskContactRef(id=2, display_name="Grace", photo_url=None),
                    ],
                )
            )
        )

        (row,) = section.tasks
        assert [(c.id, c.display_name, c.photo_url) for c in row.contacts] == [
            (5, "Ada", "/a.png"),
            (2, "Grace", None),
        ]

    def test_a_task_with_no_contacts_carries_an_empty_tuple(self) -> None:
        """W27 renders nothing for zero contacts, so it must not be null."""
        section = tasks_section_for(selected(make_model(12, due_date=TODAY)))

        (row,) = section.tasks
        assert row.contacts == ()

    def test_it_refuses_to_project_a_task_that_was_never_persisted(self) -> None:
        """A row without an id would give the card nothing to mark done.

        Unreachable through the read service, which only ever assembles what a
        repository handed back, so this fails loudly rather than rendering a
        ``task_id`` of zero that no ``PATCH`` could reach.
        """
        model = make_model(12, due_date=TODAY)
        unpersisted = TaskReadModel(
            task=Task(
                user_id=USER_ID,
                text="never saved",
                creating_journal_id=CREATING_JOURNAL_ID,
                due_journal_id=model.due_journal.id,
            ),
            creating_journal=model.creating_journal,
            due_journal=model.due_journal,
            intermediate_journals=(),
            contacts=(),
            lapse_reason=None,
        )

        with pytest.raises(ValueError, match="persisted"):
            tasks_section_for(
                UpcomingTasks(window=upcoming_window(TODAY), tasks=(unpersisted,))
            )


class TestDaysAway:
    """The number the relative due chip is drawn from (**W25**)."""

    @pytest.mark.parametrize(
        ("offset", "expected"),
        [(0, 0), (1, 1), (2, 2), (7, 7)],
        ids=["today", "tomorrow", "the day after", "the window's far day"],
    )
    def test_it_counts_from_the_windows_first_day(
        self, offset: int, expected: int
    ) -> None:
        section = tasks_section_for(
            selected(make_model(1, due_date=TODAY + datetime.timedelta(days=offset)))
        )

        (row,) = section.tasks
        assert row.days_away == expected

    def test_it_is_counted_from_the_window_and_not_from_the_machines_today(
        self,
    ) -> None:
        """The whole reason the number is published rather than derived.

        The window here is anchored on a day that is not the system's, which is
        the situation of every user whose configured zone has already turned
        over. A projection reading ``date.today()`` would answer a number
        hundreds of days out; one reading the window answers the same 0 it will
        answer tomorrow.
        """
        section = tasks_section_for(
            select_upcoming_tasks(
                [make_model(1, due_date=TODAY)], upcoming_window(TODAY)
            )
        )

        (row,) = section.tasks
        assert row.days_away == 0
        assert section.window.first_day == TODAY


class TestWhatTheProjectionDoesNotDecide:
    def test_it_preserves_the_order_the_selection_settled_on(self) -> None:
        """Soonest first, ties by task id — decided upstream, copied here."""
        section = tasks_section_for(
            selected(
                make_model(3, due_date=TODAY + datetime.timedelta(days=5)),
                make_model(2, due_date=TODAY),
                make_model(1, due_date=TODAY),
            )
        )

        assert [row.task_id for row in section.tasks] == [1, 2, 3]

    def test_it_caps_nothing(self) -> None:
        """The whole window travels; the five-item cap is the card's.

        Capping here would turn the show-more into a second request, which is
        the tradeoff the phase explicitly declined for both evidence sections.
        """
        models = [
            make_model(index, due_date=TODAY + datetime.timedelta(days=index % 8))
            for index in range(1, 13)
        ]

        section = tasks_section_for(selected(*models))

        assert len(section.tasks) == 12

    def test_it_drops_nothing_the_selection_kept(self) -> None:
        """A done task never reaches the projection, and it removes none itself.

        The exclusions belong to ``select_upcoming_tasks`` and are pinned
        against it. What is asserted here is only that the projection is a
        faithful copy of whatever survived.
        """
        upcoming = selected(
            make_model(1, due_date=TODAY),
            make_model(2, due_date=TODAY, status=TaskStatus.DONE),
        )

        section = tasks_section_for(upcoming)

        assert [row.task_id for row in section.tasks] == [1]
        assert len(upcoming.tasks) == 1


class TestTheWindowTravels:
    def test_it_carries_the_window_the_tasks_were_selected_for(self) -> None:
        section = tasks_section_for(selected(make_model(1, due_date=TODAY)))

        assert section.window.first_day == TODAY
        assert section.window.last_day == datetime.date(2026, 8, 18)
        assert section.window.days_ahead == 7

    def test_an_empty_window_is_still_a_window(self) -> None:
        """The case that needs the window: no row can supply one."""
        section = tasks_section_for(selected())

        assert section.tasks == ()
        assert section.window.first_day == TODAY
        assert section.window.last_day == datetime.date(2026, 8, 18)
