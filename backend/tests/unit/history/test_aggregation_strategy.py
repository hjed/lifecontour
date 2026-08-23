"""Unit tests for the per-root history aggregation strategy registry."""

import pytest

from app.core.history.models import (
    UnknownAggregationRootError,
    get_aggregation_strategy,
)


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
