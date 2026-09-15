"""Unit tests for contact summary API schemas."""

from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.entities import SummaryDisabledReason
from pydantic import ValidationError

from app.api.contacts.schemas import (
    ContactAttributes,
    ContactSummaryAttributes,
    ContactSummaryResource,
    ContactSummaryUpdateData,
)


@pytest.mark.unit
class TestContactSummaryAttributes:
    """Test ContactSummaryAttributes Pydantic model."""

    def test_serialize_generated_summary(self):
        """Test serialization with all fields populated."""
        now = datetime.now(tz=UTC)
        attrs = ContactSummaryAttributes(
            summary_text="John is a colleague at Acme Corp.",
            follow_up_suggestions=["Send follow-up email", "Schedule meeting"],
            status="generated",
            is_disabled=False,
            is_user_override=False,
            user_override_text=None,
            generated_at=now,
        )
        assert attrs.summary_text == "John is a colleague at Acme Corp."
        assert len(attrs.follow_up_suggestions) == 2
        assert attrs.status == "generated"
        assert attrs.is_disabled is False
        assert attrs.is_user_override is False
        assert attrs.generated_at == now

    def test_serialize_pending_summary(self):
        """Test serialization with pending state (no text)."""
        attrs = ContactSummaryAttributes(
            summary_text=None,
            follow_up_suggestions=[],
            status="pending",
            is_disabled=False,
            is_user_override=False,
        )
        assert attrs.summary_text is None
        assert attrs.follow_up_suggestions == []
        assert attrs.status == "pending"

    def test_serialize_disabled_summary(self):
        """Test serialization with disabled state."""
        attrs = ContactSummaryAttributes(
            summary_text=None,
            follow_up_suggestions=[],
            status="disabled",
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
            is_user_override=False,
        )
        assert attrs.is_disabled is True
        assert attrs.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY
        assert attrs.model_dump(mode="json")["disabled_reason"] == "low_activity"
        assert attrs.status == "disabled"

    def test_disabled_reason_defaults_to_none(self):
        """An enabled summary has no disabled reason."""
        attrs = ContactSummaryAttributes(status="pending")
        assert attrs.disabled_reason is None

    def test_unknown_disabled_reason_rejected(self):
        """Only the known reasons are valid."""
        with pytest.raises(ValidationError):
            ContactSummaryAttributes.model_validate(
                {"status": "disabled", "disabled_reason": "bored"}
            )

    def test_serialize_user_override(self):
        """Test serialization with user override text."""
        attrs = ContactSummaryAttributes(
            summary_text="AI text",
            follow_up_suggestions=[],
            status="generated",
            is_disabled=False,
            is_user_override=True,
            user_override_text="My custom summary.",
        )
        assert attrs.is_user_override is True
        assert attrs.user_override_text == "My custom summary."

    def test_default_values(self):
        """Test default values for optional fields."""
        attrs = ContactSummaryAttributes(
            status="pending",
            is_disabled=False,
            is_user_override=False,
        )
        assert attrs.summary_text is None
        assert attrs.follow_up_suggestions == []
        assert attrs.user_override_text is None
        assert attrs.generated_at is None


@pytest.mark.unit
class TestContactSummaryResource:
    """Test ContactSummaryResource model."""

    def test_resource_structure(self):
        """Test resource has correct type and structure."""
        resource = ContactSummaryResource(
            id="42",
            attributes=ContactSummaryAttributes(
                summary_text="Test summary",
                follow_up_suggestions=["Follow up"],
                status="generated",
                is_disabled=False,
                is_user_override=False,
            ),
        )
        assert resource.type == "contact_summaries"
        assert resource.id == "42"
        assert resource.attributes.summary_text == "Test summary"


@pytest.mark.unit
class TestContactSummaryUpdateData:
    """Test ContactSummaryUpdateData request model."""

    def test_disable_request(self):
        """Test disabling summary generation."""
        data = ContactSummaryUpdateData(is_disabled=True)
        assert data.is_disabled is True
        assert data.user_override_text is None

    def test_override_request(self):
        """Test setting user override text."""
        data = ContactSummaryUpdateData(user_override_text="My custom summary.")
        assert data.user_override_text == "My custom summary."

    def test_clear_override(self):
        """Test clearing user override by setting to None."""
        data = ContactSummaryUpdateData(user_override_text=None)
        assert data.user_override_text is None

    def test_empty_request_is_valid(self):
        """Test that an empty update request is valid (no changes)."""
        data = ContactSummaryUpdateData()
        assert data.is_disabled is None
        assert data.user_override_text is None

    def test_override_text_too_long_raises_error(self):
        """Test that override text exceeding max length raises validation error."""
        with pytest.raises(ValidationError):
            ContactSummaryUpdateData(user_override_text="x" * 10001)


@pytest.mark.unit
class TestContactAttributesWithSummary:
    """Test ContactAttributes includes summary field."""

    def test_summary_is_none_when_not_present(self):
        """Test summary defaults to None in ContactAttributes."""
        attrs = ContactAttributes(
            first_name="John",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        assert attrs.summary is None

    def test_summary_present_in_attributes(self):
        """Test summary is included in ContactAttributes when set."""
        summary = ContactSummaryResource(
            id="1",
            attributes=ContactSummaryAttributes(
                summary_text="Test summary",
                follow_up_suggestions=[],
                status="generated",
                is_disabled=False,
                is_user_override=False,
            ),
        )
        attrs = ContactAttributes(
            first_name="John",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
            summary=summary,
        )
        assert attrs.summary is not None
        assert attrs.summary.attributes.summary_text == "Test summary"
