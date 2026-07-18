"""Unit tests for journal tag API schemas."""

import pytest
from pydantic import ValidationError

from app.api.journals.schemas import JournalTagCreateAttributes


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
