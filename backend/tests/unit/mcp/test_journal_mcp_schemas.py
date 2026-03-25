import pytest
from pydantic import ValidationError

from app.mcp.domains.journals.schemas import JournalUpdateRequest


def test_journal_update_request_accepts_parent_id():
    """Test that JournalUpdateRequest accepts and parses parent_id."""
    # Valid parent_id
    request = JournalUpdateRequest(title="Updated Title", parent_id=2)
    assert request.parent_id == 2

    # Null parent_id (explicitly removing parent) — should be in model_fields_set
    request_null = JournalUpdateRequest(title="Updated Title", parent_id=None)
    assert request_null.parent_id is None
    assert "parent_id" in request_null.model_fields_set

    # Missing parent_id (not changing parent) — should NOT be in model_fields_set
    request_missing = JournalUpdateRequest(title="Updated Title")
    assert request_missing.parent_id is None
    assert "parent_id" not in request_missing.model_fields_set


def test_journal_update_request_invalid_parent_id():
    """Test that JournalUpdateRequest rejects invalid parent_id types."""
    with pytest.raises(ValidationError):
        JournalUpdateRequest(
            title="Updated Title",
            parent_id="not-an-int",  # type: ignore
        )
