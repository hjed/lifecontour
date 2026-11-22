"""Unit tests for where ``create_task`` puts a task, decided from its arguments.

One tool creates a task either **in journals** (both anchors, as before) or **on
a list** (the list, optionally a due date or a due journal, never both). A JSON schema cannot say "these two,
or that one", so the tool decides, and refuses any other mix by naming the
argument at fault — before anything is read or written.
"""

import datetime

import pytest
from core_shared.models.tasks import TaskValidationError

from app.mcp.domains.tasks.placement import (
    InJournals,
    OnList,
    resolve_create_placement,
)

CREATING = 11
DUE = 22
LIST = 99
DAY = datetime.date(2026, 11, 30)


def test_both_journals_place_the_task_in_journals() -> None:
    placement = resolve_create_placement(
        creating_journal_id=CREATING,
        due_journal_id=DUE,
        task_list_id=None,
        due_date=None,
    )

    assert placement == InJournals(creating_journal_id=CREATING, due_journal_id=DUE)


def test_a_list_alone_places_an_undated_task_on_it() -> None:
    placement = resolve_create_placement(
        creating_journal_id=None,
        due_journal_id=None,
        task_list_id=LIST,
        due_date=None,
    )

    assert placement == OnList(task_list_id=LIST, due_date=None, due_journal_id=None)


def test_a_list_and_a_due_date_place_a_dated_task_on_it() -> None:
    placement = resolve_create_placement(
        creating_journal_id=None,
        due_journal_id=None,
        task_list_id=LIST,
        due_date=DAY,
    )

    assert placement == OnList(task_list_id=LIST, due_date=DAY, due_journal_id=None)


def test_a_list_and_a_due_journal_place_a_task_due_in_it_on_the_list() -> None:
    placement = resolve_create_placement(
        creating_journal_id=None,
        due_journal_id=DUE,
        task_list_id=LIST,
        due_date=None,
    )

    assert placement == OnList(task_list_id=LIST, due_date=None, due_journal_id=DUE)


@pytest.mark.parametrize(
    ("arguments", "field", "says"),
    [
        pytest.param(
            {"creating_journal_id": CREATING, "task_list_id": LIST},
            "creating_journal_id",
            "no creating journal",
            id="a list and a creating journal",
        ),
        pytest.param(
            {"due_journal_id": DUE, "task_list_id": LIST, "due_date": DAY},
            "due_date",
            "never both",
            id="a list with both a due date and a due journal",
        ),
        pytest.param(
            {
                "creating_journal_id": CREATING,
                "due_journal_id": DUE,
                "task_list_id": LIST,
            },
            "creating_journal_id",
            "no creating journal",
            id="a list with both journals",
        ),
        pytest.param(
            {"creating_journal_id": CREATING, "due_journal_id": DUE, "due_date": DAY},
            "due_date",
            "on a list",
            id="a due date without a list",
        ),
        pytest.param(
            {"due_date": DAY},
            "due_date",
            "on a list",
            id="only a due date",
        ),
        pytest.param(
            {"creating_journal_id": CREATING},
            "due_journal_id",
            "task_list_id",
            id="only the creating journal",
        ),
        pytest.param(
            {"due_journal_id": DUE},
            "creating_journal_id",
            "task_list_id",
            id="only the due journal",
        ),
        pytest.param(
            {},
            "task_list_id",
            "creating_journal_id and due_journal_id",
            id="nothing at all",
        ),
    ],
)
def test_any_other_mix_is_refused_naming_the_argument(
    arguments: dict[str, object], field: str, says: str
) -> None:
    given: dict[str, object] = {
        "creating_journal_id": None,
        "due_journal_id": None,
        "task_list_id": None,
        "due_date": None,
        **arguments,
    }

    with pytest.raises(TaskValidationError) as raised:
        resolve_create_placement(**given)  # type: ignore[arg-type]

    assert raised.value.field == field
    assert says in raised.value.message
