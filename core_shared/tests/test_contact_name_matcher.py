"""Unit tests for ContactNameMatcher utility.

Tests the shared contact name matching logic used by Immich and Strava
integrations. Covers: exact match, case insensitivity, middle initial
variants, abbreviated last name, no match, and multi-match scenarios.
"""

import pytest

from core_shared.contact_name_matcher import ContactNameMatcher
from core_shared.models.contacts.entities import Contact


def _make_contact(
    first_name: str,
    last_name: str | None = None,
    middle_name: str | None = None,
    contact_id: int | None = None,
) -> Contact:
    """Helper to create a Contact with just name fields."""
    return Contact(
        user_id="user-1",
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        id=contact_id,
    )


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------


class TestParseName:
    """Tests for parse_name: splitting a full name string into parts."""

    def test_first_and_last_name(self) -> None:
        """'John Smith' → ('John', 'Smith')."""
        first, last = ContactNameMatcher.parse_name("John Smith")
        assert first == "John"
        assert last == "Smith"

    def test_single_name(self) -> None:
        """'Madonna' → ('Madonna', None)."""
        first, last = ContactNameMatcher.parse_name("Madonna")
        assert first == "Madonna"
        assert last is None

    def test_three_part_name(self) -> None:
        """'John Michael Smith' → ('John Michael', 'Smith')."""
        first, last = ContactNameMatcher.parse_name("John Michael Smith")
        assert first == "John Michael"
        assert last == "Smith"

    def test_whitespace_handling(self) -> None:
        """Leading/trailing whitespace is stripped."""
        first, last = ContactNameMatcher.parse_name("  John Smith  ")
        assert first == "John"
        assert last == "Smith"

    def test_empty_string(self) -> None:
        """Empty string returns empty first name and None last name."""
        first, last = ContactNameMatcher.parse_name("")
        assert first == ""
        assert last is None

    def test_multiple_spaces(self) -> None:
        """Multiple spaces between parts are handled gracefully."""
        first, last = ContactNameMatcher.parse_name("John   Smith")
        assert first == "John"
        assert last == "Smith"


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------


class TestFindMatches:
    """Tests for find_matches: matching a name string to contacts."""

    @pytest.fixture()
    def contacts(self) -> list[Contact]:
        """A set of contacts to match against."""
        return [
            _make_contact("John", "Smith", contact_id=1),
            _make_contact("Jane", "Doe", contact_id=2),
            _make_contact("John", "Adams", contact_id=3),
            _make_contact("Madonna", contact_id=4),
            _make_contact("John", "Smith", middle_name="Andrew", contact_id=5),
        ]

    def test_exact_match(self, contacts: list[Contact]) -> None:
        """Exact 'first last' match returns the matching contact."""
        matches = ContactNameMatcher.find_matches("Jane Doe", contacts)
        assert len(matches) == 1
        assert matches[0].id == 2

    def test_exact_match_case_insensitive(self, contacts: list[Contact]) -> None:
        """Matching is case-insensitive."""
        matches = ContactNameMatcher.find_matches("jane doe", contacts)
        assert len(matches) == 1
        assert matches[0].id == 2

    def test_multiple_exact_matches(self, contacts: list[Contact]) -> None:
        """Multiple contacts with the same name returns all matches."""
        matches = ContactNameMatcher.find_matches("John Smith", contacts)
        # Contact 1 and Contact 5 both have first=John, last=Smith
        assert len(matches) == 2
        matched_ids = {m.id for m in matches}
        assert matched_ids == {1, 5}

    def test_middle_initial_match_source_has_initial(
        self, contacts: list[Contact]
    ) -> None:
        """'John A Smith' matches 'John Smith' (with or without middle name)."""
        matches = ContactNameMatcher.find_matches("John A Smith", contacts)
        # Should match contacts 1 (no middle) and 5 (middle=Andrew, initial=A)
        matched_ids = {m.id for m in matches}
        assert 1 in matched_ids
        assert 5 in matched_ids

    def test_middle_initial_match_contact_has_initial(
        self, contacts: list[Contact]
    ) -> None:
        """Contact with middle name 'Andrew' matches 'John Smith' (no middle)."""
        # "John Smith" should match contact 5 (John Andrew Smith) as well
        matches = ContactNameMatcher.find_matches("John Smith", contacts)
        matched_ids = {m.id for m in matches}
        assert 5 in matched_ids

    def test_abbreviated_last_name(self, contacts: list[Contact]) -> None:
        """'John S' matches 'John Smith' (abbreviated last name)."""
        matches = ContactNameMatcher.find_matches("John S", contacts)
        matched_ids = {m.id for m in matches}
        assert 1 in matched_ids
        assert 5 in matched_ids

    def test_no_match(self, contacts: list[Contact]) -> None:
        """Non-matching name returns empty list."""
        matches = ContactNameMatcher.find_matches("Bob Jones", contacts)
        assert matches == []

    def test_single_name_match(self, contacts: list[Contact]) -> None:
        """'Madonna' matches contact with first_name='Madonna' and no last_name."""
        matches = ContactNameMatcher.find_matches("Madonna", contacts)
        assert len(matches) == 1
        assert matches[0].id == 4

    def test_empty_name_no_matches(self, contacts: list[Contact]) -> None:
        """Empty string returns no matches."""
        matches = ContactNameMatcher.find_matches("", contacts)
        assert matches == []

    def test_empty_contacts_list(self) -> None:
        """Empty contacts list returns no matches."""
        matches = ContactNameMatcher.find_matches("John Smith", [])
        assert matches == []

    def test_abbreviated_last_name_single_char_last(self) -> None:
        """'John S' should NOT match 'John Davis' (abbreviated last initial 'S' ≠ 'D')."""
        contacts = [_make_contact("John", "Davis", contact_id=1)]
        matches = ContactNameMatcher.find_matches("John S", contacts)
        assert matches == []

    def test_middle_initial_mismatch(self) -> None:
        """'John B Smith' should NOT match contact with middle 'Andrew' (initial A ≠ B)."""
        contacts = [
            _make_contact("John", "Smith", middle_name="Andrew", contact_id=1),
        ]
        matches = ContactNameMatcher.find_matches("John B Smith", contacts)
        # Should still match because first and last match, and the contact's
        # middle initial (A) doesn't equal B, but the spec says middle initial
        # matching means "with or without middle initials". So "John B Smith"
        # should NOT match "John Andrew Smith" since B ≠ A.
        assert matches == []
