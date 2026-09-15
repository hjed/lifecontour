"""Unit tests for ContactSummary domain entity and SummaryStatus enum."""

from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)


@pytest.mark.unit
class TestSummaryStatus:
    """Test SummaryStatus enum values."""

    def test_enum_values(self):
        """Test all expected enum values exist."""
        assert SummaryStatus.PENDING.value == "pending"
        assert SummaryStatus.GENERATING.value == "generating"
        assert SummaryStatus.GENERATED.value == "generated"
        assert SummaryStatus.FAILED.value == "failed"
        assert SummaryStatus.DISABLED.value == "disabled"

    def test_enum_from_string(self):
        """Test creating enum from string value."""
        assert SummaryStatus("pending") == SummaryStatus.PENDING
        assert SummaryStatus("generated") == SummaryStatus.GENERATED

    def test_invalid_status_raises_error(self):
        """Test invalid status string raises ValueError."""
        with pytest.raises(ValueError):
            SummaryStatus("invalid_status")

    def test_str_representation(self):
        """Test string representation of enum values."""
        assert str(SummaryStatus.PENDING) == "pending"
        assert str(SummaryStatus.GENERATED) == "generated"


@pytest.mark.unit
class TestSummaryDisabledReason:
    """Test SummaryDisabledReason enum values."""

    def test_enum_values(self):
        """Both reasons a summary can be disabled for are persisted as strings."""
        assert SummaryDisabledReason.USER.value == "user"
        assert SummaryDisabledReason.LOW_ACTIVITY.value == "low_activity"


@pytest.mark.unit
class TestContactSummary:
    """Test ContactSummary entity."""

    def test_create_summary_minimal(self):
        """Test creating summary with minimal required fields (default pending state)."""
        summary = ContactSummary(contact_id=1)
        assert summary.contact_id == 1
        assert summary.id is None
        assert summary.summary_text is None
        assert summary.follow_up_suggestions == []
        assert summary.status == SummaryStatus.PENDING
        assert summary.is_disabled is False
        assert summary.is_user_override is False
        assert summary.user_override_text is None
        assert summary.generated_at is None

    def test_create_summary_generated(self):
        """Test creating a fully generated summary."""
        now = datetime.now(tz=UTC)
        summary = ContactSummary(
            contact_id=1,
            id=42,
            summary_text="John is a colleague who works at Acme Corp.",
            follow_up_suggestions=["Send follow-up email", "Schedule meeting"],
            status=SummaryStatus.GENERATED,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        assert summary.contact_id == 1
        assert summary.id == 42
        assert summary.summary_text == "John is a colleague who works at Acme Corp."
        assert summary.follow_up_suggestions == [
            "Send follow-up email",
            "Schedule meeting",
        ]
        assert summary.status == SummaryStatus.GENERATED
        assert summary.generated_at == now

    def test_create_disabled_summary(self):
        """Test creating a disabled summary."""
        summary = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        assert summary.is_disabled is True
        assert summary.disabled_reason == SummaryDisabledReason.USER
        assert summary.status == SummaryStatus.DISABLED

    def test_enabled_summary_has_no_disabled_reason(self):
        """An enabled summary defaults to no disabled reason."""
        summary = ContactSummary(contact_id=1)
        assert summary.disabled_reason is None
        assert summary.is_user_disabled is False

    def test_disabled_without_reason_is_rejected(self):
        """A disabled summary must say why it is disabled."""
        with pytest.raises(ValueError, match="disabled_reason"):
            ContactSummary(contact_id=1, is_disabled=True)

    def test_reason_without_disabled_is_rejected(self):
        """A reason on an enabled summary is contradictory."""
        with pytest.raises(ValueError, match="disabled_reason"):
            ContactSummary(
                contact_id=1, disabled_reason=SummaryDisabledReason.LOW_ACTIVITY
            )

    def test_is_user_disabled_only_for_user_reason(self):
        """Only a user's choice counts as user-disabled; auto-pause does not."""
        user = ContactSummary(
            contact_id=1, is_disabled=True, disabled_reason=SummaryDisabledReason.USER
        )
        paused = ContactSummary(
            contact_id=1,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        assert user.is_user_disabled is True
        assert paused.is_user_disabled is False

    def test_disable_sets_flag_reason_and_status(self):
        """disable() records the reason alongside the flag and DISABLED status."""
        summary = ContactSummary(contact_id=1, status=SummaryStatus.GENERATED)

        summary.disable(SummaryDisabledReason.LOW_ACTIVITY)

        assert summary.is_disabled is True
        assert summary.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY
        assert summary.status == SummaryStatus.DISABLED

    def test_enable_clears_flag_and_reason(self):
        """enable() clears both the flag and the reason, leaving status to the caller."""
        summary = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )

        summary.enable()

        assert summary.is_disabled is False
        assert summary.disabled_reason is None
        assert summary.status == SummaryStatus.DISABLED

    def test_create_user_override_summary(self):
        """Test creating a summary with user override text."""
        summary = ContactSummary(
            contact_id=1,
            is_user_override=True,
            user_override_text="My custom summary for this contact.",
            status=SummaryStatus.GENERATED,
        )
        assert summary.is_user_override is True
        assert summary.user_override_text == "My custom summary for this contact."

    def test_follow_up_suggestions_default_empty_list(self):
        """Test follow_up_suggestions defaults to empty list."""
        summary = ContactSummary(contact_id=1)
        assert summary.follow_up_suggestions == []
        assert isinstance(summary.follow_up_suggestions, list)

    def test_get_display_text_returns_override_when_set(self):
        """Test get_display_text prefers override text when available."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="AI generated text",
            is_user_override=True,
            user_override_text="User written text",
            status=SummaryStatus.GENERATED,
        )
        assert summary.get_display_text() == "User written text"

    def test_get_display_text_returns_summary_when_no_override(self):
        """Test get_display_text returns AI text when no override."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="AI generated text",
            status=SummaryStatus.GENERATED,
        )
        assert summary.get_display_text() == "AI generated text"

    def test_get_display_text_returns_none_when_pending(self):
        """Test get_display_text returns None when pending."""
        summary = ContactSummary(contact_id=1, status=SummaryStatus.PENDING)
        assert summary.get_display_text() is None

    def test_get_display_text_returns_none_when_disabled(self):
        """Test get_display_text returns None when disabled."""
        summary = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        assert summary.get_display_text() is None

    def test_get_display_text_returns_none_when_generating(self):
        """Test get_display_text returns None when status is GENERATING."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="Stale text from previous run",
            status=SummaryStatus.GENERATING,
        )
        assert summary.get_display_text() is None

    def test_get_display_text_returns_none_when_failed(self):
        """Test get_display_text returns None when status is FAILED."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="Stale text from previous run",
            status=SummaryStatus.FAILED,
        )
        assert summary.get_display_text() is None

    def test_get_display_text_returns_override_regardless_of_status(self):
        """Test get_display_text returns user override even for non-GENERATED status."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="AI text",
            is_user_override=True,
            user_override_text="User text",
            status=SummaryStatus.PENDING,
        )
        assert summary.get_display_text() == "User text"


@pytest.mark.unit
class TestContactWithSummary:
    """Test Contact aggregate with summary field."""

    def test_contact_has_optional_summary_field(self):
        """Test Contact has summary field that defaults to None."""
        contact = Contact(first_name="John")
        assert contact.summary is None

    def test_contact_with_summary(self):
        """Test Contact can hold a summary entity."""
        summary = ContactSummary(
            contact_id=1,
            summary_text="A test summary",
            status=SummaryStatus.GENERATED,
        )
        contact = Contact(first_name="John", id=1, summary=summary)
        assert contact.summary is not None
        assert contact.summary.summary_text == "A test summary"
        assert contact.summary.status == SummaryStatus.GENERATED
