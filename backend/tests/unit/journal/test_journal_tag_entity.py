"""Unit tests for JournalTag entity."""

from uuid import uuid4

import pytest

from app.core.journal.models.journal_tag import JournalTag
from tests.integration.contact_seeding import TEST_USER_ID


@pytest.mark.unit
class TestJournalTag:
    """Test JournalTag entity."""

    def test_create_tag_minimal(self):
        """Test creating tag with minimal required fields."""
        tag = JournalTag(user_id=TEST_USER_ID, name="work")
        assert tag.name == "work"
        assert tag.id is None
        assert tag.parent_id is None
        assert tag.color is None
        assert tag.description is None

    def test_create_tag_with_all_fields(self):
        """Test creating tag with all fields."""
        tag_id = uuid4()
        parent_id = uuid4()
        tag = JournalTag(
            user_id=TEST_USER_ID,
            name="important",
            id=tag_id,
            parent_id=parent_id,
            color="#FF0000",
            description="Entries that need follow-up",
        )
        assert tag.name == "important"
        assert tag.id == tag_id
        assert tag.parent_id == parent_id
        assert tag.color == "#FF0000"
        assert tag.description == "Entries that need follow-up"

    def test_create_tag_empty_name_raises_error(self):
        """Test creating tag with empty name raises error."""
        with pytest.raises(ValueError, match="Tag name cannot be empty"):
            JournalTag(user_id=TEST_USER_ID, name="")

    def test_create_tag_whitespace_name_raises_error(self):
        """Test creating tag with whitespace-only name raises error."""
        with pytest.raises(ValueError, match="Tag name cannot be empty"):
            JournalTag(user_id=TEST_USER_ID, name="   ")

    def test_create_tag_name_too_long_raises_error(self):
        """Test creating tag with name exceeding max length raises error."""
        long_name = "a" * 101
        with pytest.raises(ValueError, match="Tag name cannot exceed 100 characters"):
            JournalTag(user_id=TEST_USER_ID, name=long_name)

    def test_create_tag_invalid_color_no_hash_raises_error(self):
        """Test creating tag with invalid color (no hash) raises error."""
        with pytest.raises(
            ValueError, match="Color must be a hex color code starting with #"
        ):
            JournalTag(user_id=TEST_USER_ID, name="work", color="FF0000")

    def test_create_tag_invalid_color_wrong_length_raises_error(self):
        """Test creating tag with invalid color (wrong length) raises error."""
        with pytest.raises(
            ValueError, match="Color must be a 7-character hex color code"
        ):
            JournalTag(user_id=TEST_USER_ID, name="work", color="#FF00")

    def test_create_tag_invalid_color_non_hex_raises_error(self):
        """Test creating tag with invalid hex characters raises error."""
        with pytest.raises(ValueError, match="Invalid hex color code"):
            JournalTag(user_id=TEST_USER_ID, name="work", color="#GGGGGG")

    def test_create_tag_valid_color(self):
        """Test creating tag with valid color."""
        tag = JournalTag(user_id=TEST_USER_ID, name="work", color="#FF0000")
        assert tag.color == "#FF0000"

    def test_create_tag_valid_color_lowercase(self):
        """Test creating tag with valid lowercase hex color."""
        tag = JournalTag(user_id=TEST_USER_ID, name="work", color="#ff0000")
        assert tag.color == "#ff0000"

    def test_tag_equality_by_id(self):
        """Test tag equality is based on ID."""
        tag_id = uuid4()
        tag1 = JournalTag(user_id=TEST_USER_ID, name="work", id=tag_id)
        tag2 = JournalTag(user_id=TEST_USER_ID, name="different", id=tag_id)
        assert tag1 == tag2

    def test_tag_inequality_different_ids(self):
        """Test tags with different IDs are not equal."""
        tag1 = JournalTag(user_id=TEST_USER_ID, name="work", id=uuid4())
        tag2 = JournalTag(user_id=TEST_USER_ID, name="work", id=uuid4())
        assert tag1 != tag2

    def test_tag_hash_by_id(self):
        """Test tag hash is based on ID."""
        tag_id = uuid4()
        tag1 = JournalTag(user_id=TEST_USER_ID, name="work", id=tag_id)
        tag2 = JournalTag(user_id=TEST_USER_ID, name="different", id=tag_id)
        assert hash(tag1) == hash(tag2)

    def test_tag_in_set(self):
        """Test tags can be used in sets."""
        tag_id = uuid4()
        tag1 = JournalTag(user_id=TEST_USER_ID, name="work", id=tag_id)
        tag2 = JournalTag(user_id=TEST_USER_ID, name="different", id=tag_id)
        tag_set = {tag1, tag2}
        assert len(tag_set) == 1

    def test_tag_with_parent_id(self):
        """Test creating tag with parent ID."""
        parent_id = uuid4()
        tag = JournalTag(user_id=TEST_USER_ID, name="subtag", parent_id=parent_id)
        assert tag.parent_id == parent_id

    def test_tag_none_color_valid(self):
        """Test creating tag with None color is valid."""
        tag = JournalTag(user_id=TEST_USER_ID, name="work", color=None)
        assert tag.color is None

    def test_tag_none_description_valid(self):
        """Test creating tag with an explicit None description is valid."""
        tag = JournalTag(user_id=TEST_USER_ID, name="work", description=None)
        assert tag.description is None

    def test_tag_description_does_not_affect_equality(self):
        """Test equality stays ID-based when descriptions differ."""
        tag_id = uuid4()
        tag1 = JournalTag(
            user_id=TEST_USER_ID, name="work", id=tag_id, description="one"
        )
        tag2 = JournalTag(
            user_id=TEST_USER_ID, name="work", id=tag_id, description="two"
        )
        assert tag1 == tag2
