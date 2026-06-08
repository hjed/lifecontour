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


def test_unknown_root_type_raises() -> None:
    """Requesting an unregistered root type fails clearly rather than silently."""
    with pytest.raises(UnknownAggregationRootError):
        get_aggregation_strategy("does_not_exist")
