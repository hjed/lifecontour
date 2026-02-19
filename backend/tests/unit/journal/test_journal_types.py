"""Unit tests for JournalType enum."""

import pytest

from app.core.journal.models.journal_types import JournalType


@pytest.mark.unit
class TestJournalType:
    """Test JournalType enum."""

    def test_journal_type_has_expected_values(self):
        """Test that JournalType enum has expected values."""
        assert JournalType.NOTE.value == "note"
        assert JournalType.EVENT.value == "event"
        assert JournalType.MOOD_RATING.value == "mood_rating"

    def test_journal_type_str_representation(self):
        """Test that JournalType string representation matches value."""
        assert str(JournalType.NOTE) == "note"
        assert str(JournalType.EVENT) == "event"
        assert str(JournalType.MOOD_RATING) == "mood_rating"

    def test_journal_type_value_comparison(self):
        """Test that JournalType values can be compared as strings."""
        assert JournalType.NOTE.value == "note"
        assert JournalType.EVENT.value == "event"
        assert JournalType.MOOD_RATING.value == "mood_rating"

    def test_journal_type_requires_data_table(self):
        """Test requires_data_table method."""
        # NOTE type does not require a data table
        assert JournalType.requires_data_table(JournalType.NOTE) is False

        # EVENT and MOOD_RATING types require data tables
        assert JournalType.requires_data_table(JournalType.EVENT) is True
        assert JournalType.requires_data_table(JournalType.MOOD_RATING) is True

    def test_journal_type_is_string_enum(self):
        """Test that JournalType is a string enum."""
        assert isinstance(JournalType.NOTE, str)
        assert isinstance(JournalType.EVENT, str)
        assert isinstance(JournalType.MOOD_RATING, str)

    def test_journal_type_can_be_used_in_list(self):
        """Test that JournalType can be used in lists."""
        types = [JournalType.NOTE, JournalType.EVENT]
        assert JournalType.NOTE in types
        assert JournalType.MOOD_RATING not in types

    def test_journal_type_can_be_iterated(self):
        """Test that JournalType can be iterated."""
        all_types = list(JournalType)
        assert (
            len(all_types) == 10
        )  # Updated for OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING
        assert JournalType.NOTE in all_types
        assert JournalType.EVENT in all_types
        assert JournalType.MOOD_RATING in all_types
        assert JournalType.PLAN in all_types
        assert JournalType.TRAVEL in all_types
        assert JournalType.PHOTO_ALBUM in all_types
        assert JournalType.FITNESS in all_types
        assert JournalType.OUTDOOR_ACTIVITY in all_types
        assert JournalType.BUSHWALKING in all_types
        assert JournalType.JOGGING in all_types
