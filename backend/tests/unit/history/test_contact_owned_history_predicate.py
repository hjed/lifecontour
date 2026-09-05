"""The one predicate saying which ``field_history`` rows belong to a contact.

Two reads need that answer: the contact history feed, and the importance signals
that rank contacts in search and on the home dashboard. They had two copies of
it, and the copies disagreed — the importance one tested the four child
``entity_type`` values and the union of the four child id sets *independently*,
so a note numbered 5 counted for any contact owning a method numbered 5 (#1396).

These tests pin the two properties that stop that recurring: every branch names
one table, and both callers render from this function rather than spelling it
out again.
"""

from app.core.contacts.adapters.sql.contact_importance_repository import (
    _IMPORTANCE_QUERY,
)
from app.core.history.models import (
    contact_owned_history_predicate,
    get_aggregation_strategy,
)

# The types and the one table each is drawn from. A tag change records the
# *tag's* id, not the link row's, which is why the pairing is data rather than a
# name derived from the type.
PAIRINGS = (
    ("contact_method", "contact_methods"),
    ("contact_address", "contact_addresses"),
    ("contact_note", "contact_notes"),
    ("contact_tag", "contact_tags"),
)


def _branches(predicate: str) -> list[str]:
    """The predicate's ``OR``-joined branches, one per line as rendered."""
    return [line.strip().removeprefix("OR ") for line in predicate.splitlines()]


class TestEveryBranchNamesOneTable:
    """The property the bug violated, asserted directly."""

    def test_each_child_type_is_paired_with_its_own_table(self) -> None:
        """``('contact_note', 5)`` may only be matched against ``contact_notes``."""
        branches = _branches(contact_owned_history_predicate(":root_id"))

        for entity_type, table in PAIRINGS:
            matching = [b for b in branches if f"= '{entity_type}'" in b]
            assert len(matching) == 1
            assert f"FROM {table} " in matching[0]
            for _, other_table in PAIRINGS:
                if other_table != table:
                    assert other_table not in matching[0]

    def test_no_branch_draws_its_ids_from_a_union_of_tables(self) -> None:
        """A ``UNION`` of every child table is what unpaired the type from the id.

        The shape reads as the same predicate and is not, so it is refused here
        rather than left to a reviewer to notice a second time.
        """
        assert "UNION" not in contact_owned_history_predicate(":root_id")

    def test_the_contact_itself_is_matched_by_id_with_no_subquery(self) -> None:
        """A change to the contact row is the simplest branch: type and id."""
        branches = _branches(contact_owned_history_predicate(":root_id"))

        assert branches[0] == "(entity_type = 'contact' AND entity_id = :root_id)"


class TestRenderingForACaller:
    """The two things the callers differ in, and nothing else."""

    def test_the_root_is_the_expression_the_caller_gives(self) -> None:
        """A bind parameter for a single-contact read, a column for a lateral."""
        predicate = contact_owned_history_predicate("c.id")

        assert "entity_id = c.id" in predicate
        assert ":root_id" not in predicate

    def test_columns_are_unqualified_without_an_alias(self) -> None:
        """The feed's statement selects from ``field_history`` with no alias."""
        predicate = contact_owned_history_predicate(":root_id")

        assert "entity_type = 'contact'" in predicate
        assert "fh." not in predicate

    def test_an_alias_qualifies_the_field_history_columns_only(self) -> None:
        """The alias belongs to ``field_history``; the child tables are their own."""
        predicate = contact_owned_history_predicate("c.id", table_alias="fh")

        assert "fh.entity_type = 'contact_note'" in predicate
        assert "fh.contact_id" not in predicate
        assert "SELECT id FROM contact_notes WHERE contact_id = c.id" in predicate


class TestBothReadsRenderFromIt:
    """Neither caller may spell the predicate out for itself again."""

    def test_the_contact_history_feed_uses_it(self) -> None:
        """Its further branches are appended after this fragment, not instead."""
        where_clause = get_aggregation_strategy("contact").where_clause

        assert contact_owned_history_predicate(":root_id") in where_clause
        # The feed reaches rows an activity count deliberately does not.
        assert "contact_relationship" in where_clause

    def test_the_importance_read_uses_it(self) -> None:
        """The read whose copy drifted; a copy again would fail here."""
        predicate = contact_owned_history_predicate(
            "c.id", table_alias="fh", indent=" " * 12
        )

        assert predicate in _IMPORTANCE_QUERY.text
