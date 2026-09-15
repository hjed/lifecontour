"""Unit tests for contact summary converter."""

from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)

from app.api.contacts.converters import ContactConverter


@pytest.mark.unit
class TestContactSummaryConverter:
    """Test ContactConverter summary-related conversion methods."""

    def test_to_summary_resource_generated(self):
        """Test converting a generated summary to API resource."""
        now = datetime.now(tz=UTC)
        summary = ContactSummary(
            contact_id=1,
            id=42,
            summary_text="John is a colleague at Acme Corp.",
            follow_up_suggestions=["Send email", "Schedule meeting"],
            status=SummaryStatus.GENERATED,
            generated_at=now,
        )
        resource = ContactConverter.to_summary_resource(summary)
        assert resource.type == "contact_summaries"
        assert resource.id == "42"
        assert resource.attributes.summary_text == "John is a colleague at Acme Corp."
        assert resource.attributes.follow_up_suggestions == [
            "Send email",
            "Schedule meeting",
        ]
        assert resource.attributes.status == "generated"
        assert resource.attributes.generated_at == now

    def test_to_summary_resource_pending(self):
        """Test converting a pending summary (no text) to API resource."""
        summary = ContactSummary(
            contact_id=1,
            id=10,
            status=SummaryStatus.PENDING,
        )
        resource = ContactConverter.to_summary_resource(summary)
        assert resource.attributes.summary_text is None
        assert resource.attributes.follow_up_suggestions == []
        assert resource.attributes.status == "pending"
        assert resource.attributes.generated_at is None

    def test_to_summary_resource_disabled(self):
        """Test converting a disabled summary to API resource."""
        summary = ContactSummary(
            contact_id=1,
            id=20,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        resource = ContactConverter.to_summary_resource(summary)
        assert resource.attributes.is_disabled is True
        assert resource.attributes.disabled_reason == SummaryDisabledReason.USER
        assert resource.attributes.status == "disabled"

    def test_to_summary_resource_enabled_has_no_disabled_reason(self):
        """An enabled summary serialises a null disabled reason."""
        summary = ContactSummary(contact_id=1, id=21, status=SummaryStatus.PENDING)
        resource = ContactConverter.to_summary_resource(summary)
        assert resource.attributes.disabled_reason is None

    def test_to_summary_resource_user_override(self):
        """Test converting a summary with user override to API resource."""
        summary = ContactSummary(
            contact_id=1,
            id=30,
            summary_text="AI generated text",
            is_user_override=True,
            user_override_text="My custom summary.",
            status=SummaryStatus.GENERATED,
        )
        resource = ContactConverter.to_summary_resource(summary)
        assert resource.attributes.is_user_override is True
        assert resource.attributes.user_override_text == "My custom summary."

    def test_to_resource_includes_summary(self):
        """Test that to_resource includes summary data in contact response."""
        summary = ContactSummary(
            contact_id=1,
            id=42,
            summary_text="Test summary",
            status=SummaryStatus.GENERATED,
        )
        contact = Contact(
            first_name="John",
            id=1,
            summary=summary,
        )
        resource = ContactConverter.to_resource(contact)
        assert resource.attributes.summary is not None
        assert resource.attributes.summary.attributes.summary_text == "Test summary"

    def test_to_resource_works_without_summary(self):
        """Test that to_resource works when contact has no summary."""
        contact = Contact(
            first_name="John",
            id=1,
        )
        resource = ContactConverter.to_resource(contact)
        assert resource.attributes.summary is None
