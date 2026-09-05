"""The precedence order contacts are ranked by, and the key that expresses it.

**Favourite, then recent journals, then recent activity.** The order was already
a fact of this system — MeiliSearch has ranked contacts by it since the search
index gained custom rules — but it lived only as a list of index-settings
strings, and ITER18-004 Phase 10 gives the dashboard a second consumer that has
to agree with it. It is therefore stated once, in ``CONTACT_IMPORTANCE_ORDER``,
and the index settings are *derived* from that tuple rather than restating it.

These tests are the ones that fail if the order changes, and they sit alongside
``tests/unit/infrastructure/search/test_ranking_rules.py``, which asserts the
same thing from the index's side and is deliberately left untouched: the two
agreeing is the point.
"""

from datetime import UTC, datetime

from app.core.contacts.models.importance import (
    CONTACT_IMPORTANCE_ORDER,
    ContactImportance,
)
from app.infrastructure.search.meilisearch_client import CONTACTS_INDEX_SETTINGS


def _importance(
    contact_id: int = 1,
    *,
    is_favourite: bool = False,
    journal_count_30d: int = 0,
    activity_count_30d: int = 0,
) -> ContactImportance:
    """One contact's signals, with everything not under test held at nothing."""
    return ContactImportance(
        contact_id=contact_id,
        is_favourite=is_favourite,
        journal_count_30d=journal_count_30d,
        activity_count_30d=activity_count_30d,
        last_activity_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestImportanceOrder:
    """The single expression of precedence."""

    def test_order_is_favourite_then_journals_then_activity(self) -> None:
        """The order is pinned: changing it has to be a deliberate edit here."""
        assert CONTACT_IMPORTANCE_ORDER == (
            "is_favourite",
            "journal_count_30d",
            "activity_count_30d",
        )

    def test_every_signal_is_a_field_of_the_model(self) -> None:
        """A name in the order with no field behind it would break ranking silently."""
        importance = _importance()
        for signal in CONTACT_IMPORTANCE_ORDER:
            assert hasattr(importance, signal), f"No {signal} on ContactImportance"

    def test_index_ranking_rules_are_derived_from_the_order(self) -> None:
        """MeiliSearch's custom rules are this tuple, descending, and nothing else."""
        ranking_rules = CONTACTS_INDEX_SETTINGS["rankingRules"]
        expected = [f"{signal}:desc" for signal in CONTACT_IMPORTANCE_ORDER]
        assert ranking_rules[-len(expected) :] == expected

    def test_no_stray_custom_rule_survives_outside_the_order(self) -> None:
        """Every descending rule in the index comes from the order, not from a literal."""
        custom_rules = [
            rule for rule in CONTACTS_INDEX_SETTINGS["rankingRules"] if ":desc" in rule
        ]
        assert custom_rules == [f"{signal}:desc" for signal in CONTACT_IMPORTANCE_ORDER]


class TestRankingKey:
    """The ordering contract callers sort by."""

    def test_favourite_outranks_more_journals_and_more_activity(self) -> None:
        """Favourite is a pin, not a tie-break: nothing below it can overturn it."""
        favourite = _importance(1, is_favourite=True)
        busy = _importance(2, journal_count_30d=50, activity_count_30d=50)

        assert favourite.ranking_key < busy.ranking_key

    def test_journal_count_breaks_a_tie_on_favourite(self) -> None:
        """Two favourites are separated by their recent journals."""
        more = _importance(1, is_favourite=True, journal_count_30d=3)
        fewer = _importance(2, is_favourite=True, journal_count_30d=1)

        assert more.ranking_key < fewer.ranking_key

    def test_activity_count_breaks_a_tie_on_favourite_and_journals(self) -> None:
        """The last signal separates contacts the first two agree about."""
        more = _importance(1, journal_count_30d=2, activity_count_30d=7)
        fewer = _importance(2, journal_count_30d=2, activity_count_30d=2)

        assert more.ranking_key < fewer.ranking_key

    def test_equal_signals_tie(self) -> None:
        """Identical signals produce identical keys, leaving the caller's order intact."""
        first = _importance(1, is_favourite=True, journal_count_30d=2)
        second = _importance(2, is_favourite=True, journal_count_30d=2)

        assert first.ranking_key == second.ranking_key

    def test_key_sorts_most_important_first_in_an_ascending_sort(self) -> None:
        """The key is negated so it composes into one ascending sort.

        The dashboard orders upcoming dates by ``(date, *importance.ranking_key)``
        — date ascending, importance descending — which only works in a single
        pass if the importance half already sorts the important contact first.
        """
        favourite = _importance(1, is_favourite=True)
        active = _importance(2, journal_count_30d=1, activity_count_30d=9)
        quiet = _importance(3)

        ordered = sorted([quiet, active, favourite], key=lambda i: i.ranking_key)

        assert [i.contact_id for i in ordered] == [1, 2, 3]

    def test_key_length_follows_the_order(self) -> None:
        """A signal added to the order extends the key without a second edit."""
        assert len(_importance().ranking_key) == len(CONTACT_IMPORTANCE_ORDER)
