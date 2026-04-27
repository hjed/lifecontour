"""
Unit tests for MeiliSearch custom ranking rules configuration.

Tests that CONTACTS_INDEX_SETTINGS includes the correct custom ranking rules
so that contact ranking reflects favourites, journal signals, and activity.
"""

from app.infrastructure.search.meilisearch_client import CONTACTS_INDEX_SETTINGS


class TestContactsRankingRules:
    """Test cases for custom ranking rules in CONTACTS_INDEX_SETTINGS."""

    def test_ranking_rules_are_configured(self):
        """Test that rankingRules key exists in CONTACTS_INDEX_SETTINGS."""
        assert "rankingRules" in CONTACTS_INDEX_SETTINGS

    def test_standard_rules_are_present(self):
        """Test that all standard MeiliSearch ranking rules are included."""
        ranking_rules = CONTACTS_INDEX_SETTINGS["rankingRules"]
        standard_rules = [
            "words",
            "typo",
            "proximity",
            "attribute",
            "sort",
            "exactness",
        ]
        for rule in standard_rules:
            assert rule in ranking_rules, (
                f"Standard rule '{rule}' missing from rankingRules"
            )

    def test_custom_rules_are_present(self):
        """Test that custom ranking rules for favourites, journal count, and activity count are present."""
        ranking_rules = CONTACTS_INDEX_SETTINGS["rankingRules"]
        custom_rules = [
            "is_favourite:desc",
            "journal_count_30d:desc",
            "activity_count_30d:desc",
        ]
        for rule in custom_rules:
            assert rule in ranking_rules, (
                f"Custom rule '{rule}' missing from rankingRules"
            )

    def test_standard_rules_precede_custom_rules(self):
        """Test that standard rules appear before custom rules in the ranking order."""
        ranking_rules = CONTACTS_INDEX_SETTINGS["rankingRules"]
        last_standard_index = max(
            ranking_rules.index(rule)
            for rule in ["words", "typo", "proximity", "attribute", "sort", "exactness"]
        )
        first_custom_index = min(
            ranking_rules.index(rule)
            for rule in [
                "is_favourite:desc",
                "journal_count_30d:desc",
                "activity_count_30d:desc",
            ]
        )
        assert last_standard_index < first_custom_index, (
            f"Standard rules (last at index {last_standard_index}) "
            f"should precede custom rules (first at index {first_custom_index})"
        )

    def test_is_favourite_precedes_other_custom_rules(self):
        """Test that is_favourite ranking comes before journal and activity counts."""
        ranking_rules = CONTACTS_INDEX_SETTINGS["rankingRules"]
        fav_index = ranking_rules.index("is_favourite:desc")
        journal_index = ranking_rules.index("journal_count_30d:desc")
        activity_index = ranking_rules.index("activity_count_30d:desc")
        assert fav_index < journal_index, (
            "is_favourite should precede journal_count_30d"
        )
        assert fav_index < activity_index, (
            "is_favourite should precede activity_count_30d"
        )
