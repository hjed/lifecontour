"""Unit tests for journal tag API schemas."""

import pytest
from pydantic import ValidationError

from app.api.journals.schemas import (
    JournalTagCreateAttributes,
    JournalTagMergeRequest,
    JournalTagUpdateAttributes,
)


@pytest.mark.unit
class TestJournalTagCreateAttributes:
    """Test the create-tag request attributes."""

    def test_accepts_description(self):
        """Test description is carried through when supplied."""
        attributes = JournalTagCreateAttributes(
            name="training",
            color="#00FF00",
            description="Structured training sessions",
        )
        assert attributes.description == "Structured training sessions"

    def test_description_defaults_to_none(self):
        """Test description is optional, matching the nullable column."""
        attributes = JournalTagCreateAttributes(name="training")
        assert attributes.description is None

    def test_accepts_explicit_null_description(self):
        """Test an explicit null description is valid."""
        attributes = JournalTagCreateAttributes(name="training", description=None)
        assert attributes.description is None

    def test_name_still_required(self):
        """Test adding description did not make name optional."""
        with pytest.raises(ValidationError):
            JournalTagCreateAttributes(description="No name given")  # type: ignore[call-arg]


@pytest.mark.unit
class TestJournalTagUpdateAttributes:
    """Test the update-tag request attributes.

    Mirrors the contact ``TagUpdateAttributes`` contract: every field is
    optional, an explicit null is rejected for the string fields, and an
    explicit null ``parent_id`` is the wire signal for "move to root".
    """

    def test_all_fields_optional(self):
        """Test a PATCH may supply no attributes at all."""
        attributes = JournalTagUpdateAttributes()
        assert attributes.name is None
        assert attributes.color is None
        assert attributes.description is None
        assert attributes.parent_id is None

    def test_accepts_partial_update(self):
        """Test supplying a single field leaves the rest unset."""
        attributes = JournalTagUpdateAttributes(name="training")
        assert attributes.name == "training"
        assert "color" not in attributes.model_fields_set

    @pytest.mark.parametrize("field", ["name", "color", "description"])
    def test_rejects_explicit_null_string_fields(self, field):
        """Test explicit nulls are rejected for the string fields."""
        with pytest.raises(ValidationError):
            JournalTagUpdateAttributes(**{field: None})

    def test_allows_explicit_null_parent_id(self):
        """Test an explicit null parent_id is valid and recorded as set."""
        attributes = JournalTagUpdateAttributes(parent_id=None)
        assert attributes.parent_id is None
        assert "parent_id" in attributes.model_fields_set

    def test_rejects_empty_name(self):
        """Test a blank name is rejected rather than clearing the name."""
        with pytest.raises(ValidationError):
            JournalTagUpdateAttributes(name="")


@pytest.mark.unit
class TestJournalTagMergeRequest:
    """Test the merge-tag request body.

    Mirrors the contact ``TagMergeRequest`` shape: the source tag is the path
    parameter, so the body carries only the target.
    """

    def test_accepts_valid_body(self):
        """Test a well-formed merge body parses."""
        request = JournalTagMergeRequest.model_validate(
            {
                "data": {
                    "type": "journal-tags",
                    "attributes": {"target_tag_id": "some-uuid"},
                }
            }
        )
        assert request.data.attributes.target_tag_id == "some-uuid"

    def test_type_defaults_to_journal_tags(self):
        """Test an omitted resource type defaults rather than failing."""
        request = JournalTagMergeRequest.model_validate(
            {"data": {"attributes": {"target_tag_id": "some-uuid"}}}
        )
        assert request.data.type == "journal-tags"

    def test_rejects_missing_target(self):
        """Test the target tag id is required."""
        with pytest.raises(ValidationError):
            JournalTagMergeRequest.model_validate(
                {"data": {"type": "journal-tags", "attributes": {}}}
            )
