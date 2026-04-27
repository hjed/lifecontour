"""Unit tests for JournalDailySummary entity."""

from datetime import UTC, date, datetime

from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary


class TestJournalDailySummaryEntity:
    """Test JournalDailySummary entity creation and methods."""

    def test_create_with_required_fields(self) -> None:
        """Test creating a summary with only required fields."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
        )
        assert summary.user_id == "user123"
        assert summary.summary_date == date(2026, 4, 27)
        assert summary.id is None
        assert summary.summary_text is None
        assert summary.journal_count == 0
        assert summary.event_count == 0
        assert summary.contact_count == 0
        assert summary.mood_average is None
        assert summary.status == SummaryStatus.PENDING
        assert summary.generated_at is None
        assert summary.created_at is None
        assert summary.updated_at is None

    def test_create_with_all_fields(self) -> None:
        """Test creating a summary with all fields populated."""
        now = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            id=1,
            summary_text="A busy day with meetings and a hike.",
            journal_count=5,
            event_count=3,
            contact_count=4,
            mood_average=7.5,
            status=SummaryStatus.GENERATED,
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
        assert summary.id == 1
        assert summary.summary_text == "A busy day with meetings and a hike."
        assert summary.journal_count == 5
        assert summary.event_count == 3
        assert summary.contact_count == 4
        assert summary.mood_average == 7.5
        assert summary.status == SummaryStatus.GENERATED
        assert summary.generated_at == now

    def test_status_enum_values(self) -> None:
        """Test that all expected SummaryStatus values are usable."""
        for status in [
            SummaryStatus.PENDING,
            SummaryStatus.GENERATING,
            SummaryStatus.GENERATED,
            SummaryStatus.FAILED,
            SummaryStatus.DISABLED,
        ]:
            summary = JournalDailySummary(
                user_id="user123",
                summary_date=date(2026, 4, 27),
                status=status,
            )
            assert summary.status == status


class TestJournalDailySummaryDisplayText:
    """Test get_display_text method."""

    def test_display_text_when_generated(self) -> None:
        """Test display text is returned when status is GENERATED."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Summary of the day.",
            status=SummaryStatus.GENERATED,
        )
        assert summary.get_display_text() == "Summary of the day."

    def test_display_text_none_when_pending(self) -> None:
        """Test display text returns None when status is PENDING."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Summary of the day.",
            status=SummaryStatus.PENDING,
        )
        assert summary.get_display_text() is None

    def test_display_text_none_when_generating(self) -> None:
        """Test display text returns None when status is GENERATING."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Summary of the day.",
            status=SummaryStatus.GENERATING,
        )
        assert summary.get_display_text() is None

    def test_display_text_none_when_failed(self) -> None:
        """Test display text returns None when status is FAILED."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Summary of the day.",
            status=SummaryStatus.FAILED,
        )
        assert summary.get_display_text() is None

    def test_display_text_none_when_disabled(self) -> None:
        """Test display text returns None when status is DISABLED."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Summary of the day.",
            status=SummaryStatus.DISABLED,
        )
        assert summary.get_display_text() is None

    def test_display_text_none_when_generated_but_no_text(self) -> None:
        """Test display text returns None when GENERATED but text is None."""
        summary = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text=None,
            status=SummaryStatus.GENERATED,
        )
        assert summary.get_display_text() is None
