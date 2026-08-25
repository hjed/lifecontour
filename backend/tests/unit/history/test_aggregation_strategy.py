"""Unit tests for the per-root history aggregation strategy registry."""

import pytest

from app.core.history.models import (
    UnknownAggregationRootError,
    get_aggregation_strategy,
)
from app.core.tasks.models.events import contact_field_name


def test_contact_strategy_is_registered() -> None:
    """The 'contact' strategy preserves the existing contact aggregation predicate."""
    strategy = get_aggregation_strategy("contact")

    assert strategy.root_type == "contact"
    # Parameterised on :root_id rather than a contact-specific bind name.
    assert ":root_id" in strategy.where_clause
    # Aggregates the contact itself and its related sub-entities.
    assert "entity_type = 'contact'" in strategy.where_clause
    assert "contact_methods" in strategy.where_clause
    assert "contact_addresses" in strategy.where_clause
    assert "contact_notes" in strategy.where_clause
    assert "contact_tags" in strategy.where_clause
    assert "contact_relationships" in strategy.where_clause
    assert "contact_important_dates" in strategy.where_clause
    assert "contact_summary" in strategy.where_clause


def test_journal_strategy_is_registered() -> None:
    """The 'journal' strategy aggregates rows tagged to the journal itself.

    Journal/route/gear/type changes are all projected with
    entity_type='journal', entity_id=journal_id, so the predicate keys on the
    journal directly (parameterised on :root_id).
    """
    strategy = get_aggregation_strategy("journal")

    assert strategy.root_type == "journal"
    assert ":root_id" in strategy.where_clause
    assert "entity_type = 'journal'" in strategy.where_clause
    assert "entity_id = :root_id" in strategy.where_clause


def test_unknown_root_type_raises() -> None:
    """Requesting an unregistered root type fails clearly rather than silently."""
    with pytest.raises(UnknownAggregationRootError):
        get_aggregation_strategy("does_not_exist")


def test_task_strategy_is_registered() -> None:
    """The 'task' strategy aggregates rows tagged to the task itself.

    Every task event projects with ``entity_type='task'``, ``entity_id=task_id``
    — a task has no sub-entities — so the predicate keys on the task directly.
    Notably it does **not** reach through the ``tasks`` table: a task is
    hard-deleted and its history has to stay readable afterwards, so a join to a
    row that may be gone would silently empty a deleted task's feed.
    """
    strategy = get_aggregation_strategy("task")

    assert strategy.root_type == "task"
    assert ":root_id" in strategy.where_clause
    assert "entity_type = 'task'" in strategy.where_clause
    assert "entity_id = :root_id" in strategy.where_clause
    assert "FROM tasks" not in strategy.where_clause


class TestContactStrategyReachesTaskLinkRows:
    """The contact aggregate spans the rows recording a task link to *that* contact.

    A task's contact membership is projected onto the **task**
    (``entity_type='task'``, ``entity_id=task_id``) under a per-contact field
    name, so a contact's own predicate would never see it. ITER18-003 Phase 9
    adds the one branch that does, which is what puts a task on a person's
    activity history as a read-only record.
    """

    def test_the_contact_predicate_has_a_task_branch(self) -> None:
        strategy = get_aggregation_strategy("contact")

        assert "entity_type = 'task'" in strategy.where_clause

    def test_the_branch_matches_the_field_name_the_service_builds(self) -> None:
        """The predicate spells the same key ``contact_field_name`` produces.

        Imported rather than re-spelt: the service writes these keys and this
        predicate reads them, and a format living in two places is one that can
        drift. If the prefix ever changes, this test fails rather than the
        contact feed quietly going empty.
        """
        strategy = get_aggregation_strategy("contact")
        prefix = contact_field_name(7).removesuffix("7")

        assert f"'{prefix}'" in strategy.where_clause

    def test_the_branch_binds_the_root_id_as_text(self) -> None:
        """The field name is built from a *text* bind, not the integer one.

        ``:root_id`` is compared to ``entity_id`` (an integer) everywhere else in
        this predicate; reusing it inside a string concatenation would ask
        PostgreSQL to infer two types for one parameter.
        """
        strategy = get_aggregation_strategy("contact")

        assert ":root_id_text" in strategy.where_clause

    def test_the_branch_does_not_join_the_link_table_or_the_tasks_table(self) -> None:
        """The record is keyed on the field name, never on a live link row.

        A join through ``task_contacts`` would erase the record the moment the
        task is unlinked or hard-deleted — a history feed that forgets what it
        recorded. Asserted rather than left to a comment, because the join is the
        obvious design and would pass every other test in this suite.
        """
        strategy = get_aggregation_strategy("contact")

        assert "task_contacts" not in strategy.where_clause
        assert "FROM tasks" not in strategy.where_clause


class TestContactStrategyClosesADeletedTasksStory:
    """A task the contact was linked to shows its deletion on their feed.

    Without this the feed keeps a "linked to a task" line forever for a task
    that no longer exists, and the record it exists to be reads as a commitment
    still standing. The delete marker is a *task-scoped* row (``__deleted__``),
    so the link-row branch cannot reach it.
    """

    def test_the_contact_predicate_reaches_the_delete_marker(self) -> None:
        strategy = get_aggregation_strategy("contact")

        assert "'__deleted__'" in strategy.where_clause

    def test_it_is_narrowed_to_tasks_this_contact_was_linked_to(self) -> None:
        """Every task in the database must not land on every contact's feed."""
        strategy = get_aggregation_strategy("contact")

        # The narrowing reads history itself — the only record of the link that
        # survives the task being deleted.
        assert "FROM field_history" in strategy.where_clause

    def test_it_still_joins_neither_the_link_table_nor_the_tasks_table(self) -> None:
        strategy = get_aggregation_strategy("contact")

        assert "task_contacts" not in strategy.where_clause
        assert "FROM tasks" not in strategy.where_clause
