"""Unit tests for JournalTag and JournalTagAssignment entities."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.journal.models.exceptions import (
    JournalTagAssignmentValidationError,
    JournalTagValidationError,
)
from app.core.journal.models.journal_tag import (
    MAX_TAG_NAME_LENGTH,
    JournalTag,
    JournalTagAssignment,
)


class TestJournalTag:
    """Tests for JournalTag entity."""

    def test_create_valid_tag(self):
        """Test creating a valid journal tag."""
        tag_id = uuid4()
        now = datetime.now(UTC)
        tag = JournalTag(
            id=tag_id,
            name="Work",
            color="#FF5733",
            parent_id=None,
            created_at=now,
            updated_at=now,
        )

        assert tag.id == tag_id
        assert tag.name == "Work"
        assert tag.color == "#FF5733"
        assert tag.parent_id is None
        assert tag.created_at == now
        assert tag.updated_at == now

    def test_create_tag_with_parent(self):
        """Test creating a tag with a parent (hierarchical)."""
        parent_id = uuid4()
        tag = JournalTag(
            id=uuid4(),
            name="Python",
            color="#3776AB",
            parent_id=parent_id,
        )

        assert tag.parent_id == parent_id

    def test_create_tag_without_timestamps(self):
        """Test creating a tag without timestamps (should be None)."""
        tag = JournalTag(
            id=uuid4(),
            name="Personal",
            color="#00FF00",
        )

        assert tag.created_at is None
        assert tag.updated_at is None

    def test_invalid_name_empty(self):
        """Test that tag name cannot be empty."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="",
                color="#FF0000",
            )

        assert exc_info.value.field == "name"
        assert "required" in exc_info.value.message

    def test_invalid_name_whitespace_only(self):
        """Test that tag name cannot be whitespace only."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="   ",
                color="#FF0000",
            )

        assert exc_info.value.field == "name"

    def test_invalid_name_too_long(self):
        """Test that tag name cannot exceed maximum length."""
        long_name = "a" * (MAX_TAG_NAME_LENGTH + 1)
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name=long_name,
                color="#FF0000",
            )

        assert exc_info.value.field == "name"
        assert str(MAX_TAG_NAME_LENGTH) in exc_info.value.message

    def test_valid_name_at_max_length(self):
        """Test that tag name can be exactly at maximum length."""
        max_name = "a" * MAX_TAG_NAME_LENGTH
        tag = JournalTag(
            id=uuid4(),
            name=max_name,
            color="#FF0000",
        )

        assert tag.name == max_name

    def test_invalid_color_empty(self):
        """Test that color cannot be empty."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="Test",
                color="",
            )

        assert exc_info.value.field == "color"
        assert "required" in exc_info.value.message

    def test_invalid_color_no_hash(self):
        """Test that color must start with #."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="Test",
                color="FF0000",
            )

        assert exc_info.value.field == "color"
        assert "hex format" in exc_info.value.message

    def test_invalid_color_wrong_length(self):
        """Test that color must be exactly 7 characters (#RRGGBB)."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="Test",
                color="#FF00",
            )

        assert exc_info.value.field == "color"

    def test_invalid_color_non_hex(self):
        """Test that color must contain valid hex characters."""
        with pytest.raises(JournalTagValidationError) as exc_info:
            JournalTag(
                id=uuid4(),
                name="Test",
                color="#GGGGGG",
            )

        assert exc_info.value.field == "color"
        assert "hexadecimal" in exc_info.value.message

    def test_valid_color_formats(self):
        """Test various valid color formats."""
        valid_colors = ["#000000", "#FFFFFF", "#FF5733", "#3776AB", "#00FF00"]
        for color in valid_colors:
            tag = JournalTag(
                id=uuid4(),
                name="Test",
                color=color,
            )
            assert tag.color == color


class TestJournalTagAssignment:
    """Tests for JournalTagAssignment entity."""

    def test_create_valid_assignment(self):
        """Test creating a valid journal tag assignment."""
        tag_id = uuid4()
        now = datetime.now(UTC)
        assignment = JournalTagAssignment(
            journal_id=1,
            tag_id=tag_id,
            created_at=now,
        )

        assert assignment.journal_id == 1
        assert assignment.tag_id == tag_id
        assert assignment.created_at == now

    def test_create_assignment_without_created_at(self):
        """Test creating an assignment without created_at (should be None)."""
        assignment = JournalTagAssignment(
            journal_id=1,
            tag_id=uuid4(),
        )

        assert assignment.created_at is None

    def test_invalid_journal_id_zero(self):
        """Test that journal_id cannot be zero."""
        with pytest.raises(JournalTagAssignmentValidationError) as exc_info:
            JournalTagAssignment(
                journal_id=0,
                tag_id=uuid4(),
            )

        assert exc_info.value.field == "journal_id"
        assert "positive integer" in exc_info.value.message

    def test_invalid_journal_id_negative(self):
        """Test that journal_id cannot be negative."""
        with pytest.raises(JournalTagAssignmentValidationError) as exc_info:
            JournalTagAssignment(
                journal_id=-1,
                tag_id=uuid4(),
            )

        assert exc_info.value.field == "journal_id"

