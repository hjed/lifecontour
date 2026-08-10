"""Unit tests for grouping a journal's tasks by the role each link holds.

A journal's detail view shows "the tasks it is linked to, grouped by the nature
of the link" — due here, created here, mentioned here. The rule that decides
which group a task falls in is **pure**: every fact it needs is already on the
read model, so it takes assembled models and a journal id and reads nothing.

Two things make this worth its own file rather than an assertion inside the
service tests.

**A task can hold two roles at once, and both are reachable.** Invariant 6 lets
one journal be a task's creating *and* due anchor, and retargeting onto a
journal the task already mentioned makes the due anchor a mention as well. A
grouping that assigned each task a single role would drop one of those links
silently, which is the failure the specification's three-group display exists to
prevent.

**Ordering is a promise this phase makes.** Phase 10 recorded that
``created_at`` ties for links written in one transaction, so "oldest first" is a
partial order and cannot be what a read surface guarantees. The groups are
therefore ordered by the due journal's **date**, then by task id — a total order
over rows that can genuinely tie, and one the tests below pin by constructing a
tie deliberately rather than hoping to observe one.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.tasks import (
    JournalTaskGroups,
    Task,
    TaskContactRef,
    TaskJournalRef,
    TaskLinkRole,
    TaskReadModel,
    TaskStatus,
    group_tasks_by_link_role,
)

from tests.unit.tasks.task_doubles import USER_ID

# The journal whose detail view is being rendered in every test below.
JOURNAL_ID = 100
OTHER_JOURNAL_ID = 200
THIRD_JOURNAL_ID = 300

TODAY = datetime.date(2026, 8, 9)
SOON = datetime.date(2026, 8, 11)
LATER = datetime.date(2026, 8, 20)

# CI selects by marker (``pytest -m unit``), not by path, so a file without one
# collects locally and is silently deselected there. Applied at module level
# rather than per class, which is what left it off in the first place.
pytestmark = pytest.mark.unit


def journal_ref(journal_id: int, date: datetime.date) -> TaskJournalRef:
    """A journal as a read surface sees it."""
    return TaskJournalRef(
        id=journal_id, title=f"Journal {journal_id}", date=date, cancelled=False
    )


def read_model(
    task_id: int,
    *,
    creating_journal_id: int,
    due_journal_id: int,
    due_date: datetime.date = LATER,
    mentions: tuple[int, ...] = (),
) -> TaskReadModel:
    """An assembled read model, as the service hands one to the grouping.

    Built directly rather than through ``build_task_read_model`` because these
    tests are about which group a task lands in, and the lapse derivation the
    builder performs is not part of that question.
    """
    return TaskReadModel(
        task=Task(
            id=task_id,
            user_id=USER_ID,
            text=f"task {task_id}",
            creating_journal_id=creating_journal_id,
            due_journal_id=due_journal_id,
            status=TaskStatus.NOT_DONE,
        ),
        creating_journal=journal_ref(creating_journal_id, TODAY),
        due_journal=journal_ref(due_journal_id, due_date),
        intermediate_journals=tuple(
            journal_ref(journal_id, TODAY) for journal_id in mentions
        ),
        contacts=(),
        lapse_reason=None,
    )


def task_ids(models: tuple[TaskReadModel, ...]) -> list[int | None]:
    """The ids in a group, in the order the group hands them out."""
    return [model.task.id for model in models]


class TestRoleAssignment:
    """Which group each link puts a task in."""

    def test_task_due_in_this_journal_is_grouped_under_due(self) -> None:
        """A task whose due anchor is this journal is due *here*."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    1, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
                )
            ],
        )

        assert task_ids(groups.due) == [1]
        assert groups.created == ()
        assert groups.mentioned == ()

    def test_task_created_in_this_journal_is_grouped_under_created(self) -> None:
        """A task whose creating anchor is this journal was created *here*."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    2, creating_journal_id=JOURNAL_ID, due_journal_id=OTHER_JOURNAL_ID
                )
            ],
        )

        assert task_ids(groups.created) == [2]
        assert groups.due == ()
        assert groups.mentioned == ()

    def test_task_mentioning_this_journal_is_grouped_under_mentioned(self) -> None:
        """An intermediate link is a mention, and nothing more."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    3,
                    creating_journal_id=OTHER_JOURNAL_ID,
                    due_journal_id=THIRD_JOURNAL_ID,
                    mentions=(JOURNAL_ID,),
                )
            ],
        )

        assert task_ids(groups.mentioned) == [3]
        assert groups.due == ()
        assert groups.created == ()

    def test_a_task_linked_to_another_journal_entirely_appears_nowhere(self) -> None:
        """A task with no link to this journal is in none of the three groups.

        Unreachable through the repository, whose query only returns linked
        tasks, and asserted anyway: the grouping is pure and a caller assembling
        models some other way must not have them silently filed under a role
        they do not hold.
        """
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    4,
                    creating_journal_id=OTHER_JOURNAL_ID,
                    due_journal_id=THIRD_JOURNAL_ID,
                )
            ],
        )

        assert groups.due == ()
        assert groups.created == ()
        assert groups.mentioned == ()
        assert groups.tasks == ()


class TestTwoRolesAtOnce:
    """The two shapes in which one task holds two of this journal's roles."""

    def test_invariant_six_journal_is_both_created_and_due(self) -> None:
        """A task created in the journal it is due in appears in both groups.

        Invariant 6 permits exactly this, so a grouping that picked one role
        would hide a link the specification says exists.
        """
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [read_model(5, creating_journal_id=JOURNAL_ID, due_journal_id=JOURNAL_ID)],
        )

        assert task_ids(groups.due) == [5]
        assert task_ids(groups.created) == [5]
        assert groups.mentioned == ()

    def test_retarget_onto_a_mentioned_journal_is_both_due_and_mentioned(self) -> None:
        """Retargeting onto an already-attached journal keeps the mention.

        The intermediate link row survives the retarget — the read model's
        docstring says the mentions "may include the due journal" for this
        reason — so the task is genuinely both.
        """
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    6,
                    creating_journal_id=OTHER_JOURNAL_ID,
                    due_journal_id=JOURNAL_ID,
                    mentions=(JOURNAL_ID,),
                )
            ],
        )

        assert task_ids(groups.due) == [6]
        assert task_ids(groups.mentioned) == [6]
        assert groups.created == ()

    def test_a_two_role_task_is_listed_once_among_the_unique_tasks(self) -> None:
        """``tasks`` de-duplicates, which is what the JSON:API ``data`` needs.

        JSON:API forbids the same resource appearing twice in ``data``, so the
        endpoint renders this collection and puts the roles on each resource.
        """
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [read_model(7, creating_journal_id=JOURNAL_ID, due_journal_id=JOURNAL_ID)],
        )

        assert task_ids(groups.tasks) == [7]

    def test_roles_for_reports_both_roles_in_a_fixed_order(self) -> None:
        """The roles a task holds, ordered so a response never reshuffles them."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    8,
                    creating_journal_id=JOURNAL_ID,
                    due_journal_id=JOURNAL_ID,
                    mentions=(JOURNAL_ID,),
                )
            ],
        )

        assert groups.roles_for(8) == (
            TaskLinkRole.DUE,
            TaskLinkRole.CREATED,
            TaskLinkRole.MENTIONED,
        )

    def test_roles_for_an_unlinked_task_is_empty(self) -> None:
        """A task id the grouping never saw holds no roles here."""
        groups = group_tasks_by_link_role(JOURNAL_ID, [])

        assert groups.roles_for(999) == ()


class TestOrdering:
    """The total order each group promises."""

    def test_groups_are_ordered_by_due_journal_date_soonest_first(self) -> None:
        """Across a group, the nearest deadline comes first."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    11,
                    creating_journal_id=JOURNAL_ID,
                    due_journal_id=THIRD_JOURNAL_ID,
                    due_date=LATER,
                ),
                read_model(
                    12,
                    creating_journal_id=JOURNAL_ID,
                    due_journal_id=OTHER_JOURNAL_ID,
                    due_date=SOON,
                ),
            ],
        )

        assert task_ids(groups.created) == [12, 11]

    def test_tasks_sharing_a_due_date_are_ordered_by_id(self) -> None:
        """The tie-break, constructed rather than waited for.

        Every task in the *due* group shares the journal and therefore its date,
        so this is not an edge case there — it is the whole ordering. Supplied
        out of order so a grouping that simply preserved its input would fail.
        """
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    31, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
                ),
                read_model(
                    13, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
                ),
                read_model(
                    22, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
                ),
            ],
        )

        assert task_ids(groups.due) == [13, 22, 31]

    def test_unique_tasks_use_the_same_order_as_the_groups(self) -> None:
        """One ordering rule, so ``data`` and ``meta.groups`` agree."""
        groups = group_tasks_by_link_role(
            JOURNAL_ID,
            [
                read_model(
                    14,
                    creating_journal_id=JOURNAL_ID,
                    due_journal_id=THIRD_JOURNAL_ID,
                    due_date=LATER,
                ),
                read_model(
                    15,
                    creating_journal_id=OTHER_JOURNAL_ID,
                    due_journal_id=JOURNAL_ID,
                    due_date=SOON,
                ),
            ],
        )

        assert task_ids(groups.tasks) == [15, 14]


class TestRoleFilter:
    """Narrowing the answer to one role."""

    @pytest.fixture
    def models(self) -> list[TaskReadModel]:
        """One task in each of the three roles."""
        return [
            read_model(
                21, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
            ),
            read_model(
                22, creating_journal_id=JOURNAL_ID, due_journal_id=OTHER_JOURNAL_ID
            ),
            read_model(
                23,
                creating_journal_id=OTHER_JOURNAL_ID,
                due_journal_id=THIRD_JOURNAL_ID,
                mentions=(JOURNAL_ID,),
            ),
        ]

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            (TaskLinkRole.DUE, 21),
            (TaskLinkRole.CREATED, 22),
            (TaskLinkRole.MENTIONED, 23),
        ],
    )
    def test_filtering_keeps_only_the_named_role(
        self, models: list[TaskReadModel], role: TaskLinkRole, expected: int
    ) -> None:
        """The other two groups are emptied, not removed.

        The response shape stays the same whether a filter was asked for, so a
        client parses one answer rather than two.
        """
        groups = group_tasks_by_link_role(JOURNAL_ID, models, role=role)

        assert task_ids(groups.for_role(role)) == [expected]
        assert task_ids(groups.tasks) == [expected]
        for other in TaskLinkRole:
            if other is not role:
                assert groups.for_role(other) == ()

    def test_filtering_keeps_a_two_role_task_when_either_role_is_named(self) -> None:
        """A task held by two roles answers to both filters."""
        both = [
            read_model(24, creating_journal_id=JOURNAL_ID, due_journal_id=JOURNAL_ID)
        ]

        assert task_ids(
            group_tasks_by_link_role(JOURNAL_ID, both, role=TaskLinkRole.DUE).due
        ) == [24]
        assert task_ids(
            group_tasks_by_link_role(
                JOURNAL_ID, both, role=TaskLinkRole.CREATED
            ).created
        ) == [24]

    def test_no_filter_returns_every_role(self, models: list[TaskReadModel]) -> None:
        """The default is the whole picture."""
        groups = group_tasks_by_link_role(JOURNAL_ID, models)

        assert task_ids(groups.due) == [21]
        assert task_ids(groups.created) == [22]
        assert task_ids(groups.mentioned) == [23]


class TestEmptyJournal:
    """A journal nothing is linked to."""

    def test_no_tasks_gives_three_empty_groups(self) -> None:
        """Empty rather than absent: an empty journal is a normal answer."""
        groups = group_tasks_by_link_role(JOURNAL_ID, [])

        assert groups == JournalTaskGroups(
            journal_id=JOURNAL_ID, due=(), created=(), mentioned=()
        )
        assert groups.tasks == ()

    def test_the_journal_id_is_carried_on_the_answer(self) -> None:
        """The grouping's answer says which journal it is about."""
        assert group_tasks_by_link_role(JOURNAL_ID, []).journal_id == JOURNAL_ID


class TestRoleVocabulary:
    """The wire values, pinned.

    The specification names the three groups "due", "created" and "mentioned",
    and both surfaces put those strings on the wire. A rename would be a
    breaking change to two APIs, so it fails here first.
    """

    def test_wire_values_match_the_specification_wording(self) -> None:
        """The three roles, spelled as the specification spells them."""
        assert [str(role) for role in TaskLinkRole] == [
            "due",
            "created",
            "mentioned",
        ]


class TestReadModelIsUntouched:
    """The grouping arranges models; it does not rebuild them."""

    def test_the_models_handed_out_are_the_ones_passed_in(self) -> None:
        """Identity, not equality — nothing is copied or re-derived.

        The lapse verdict and the contacts were decided by the assembler, and a
        grouping that rebuilt a model could disagree with it.
        """
        model = read_model(
            30, creating_journal_id=OTHER_JOURNAL_ID, due_journal_id=JOURNAL_ID
        )
        model_with_contacts = TaskReadModel(
            task=model.task,
            creating_journal=model.creating_journal,
            due_journal=model.due_journal,
            intermediate_journals=model.intermediate_journals,
            contacts=(TaskContactRef(id=1, display_name="Sarah", photo_url=None),),
            lapse_reason=model.lapse_reason,
        )

        groups = group_tasks_by_link_role(JOURNAL_ID, [model_with_contacts])

        assert groups.due[0] is model_with_contacts
