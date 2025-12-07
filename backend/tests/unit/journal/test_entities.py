"""Unit tests for journal domain entities."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.journal.models.constants import MAX_HIERARCHY_DEPTH, MAX_TITLE_LENGTH
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalValidationError
from app.core.journal.models.value_objects import EventDateRange


@pytest.mark.unit
class TestEventDateRange:
    """Test EventDateRange value object."""

    def test_create_valid_date_range(self):
        """Test creating a valid date range."""
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        date_range = EventDateRange(start=start, end=end)

        assert date_range.start == start
        assert date_range.end == end

    def test_create_same_start_end(self):
        """Test creating a date range with same start and end (point in time)."""
        now = datetime.now(UTC)

        date_range = EventDateRange(start=now, end=now)

        assert date_range.start == date_range.end

    def test_create_future_date_range(self):
        """Test creating a date range in the future (for planned events)."""
        future_start = datetime.now(UTC) + timedelta(days=30)
        future_end = future_start + timedelta(hours=2)

        date_range = EventDateRange(start=future_start, end=future_end)

        assert date_range.start == future_start
        assert date_range.end == future_end

    def test_invalid_date_range_end_before_start(self):
        """Test that end date before start date raises error."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)

        with pytest.raises(
            JournalValidationError,
            match="event_date_range.start must be before or equal to event_date_range.end",
        ):
            EventDateRange(start=start, end=end)

    def test_duration_property(self):
        """Test duration calculation."""
        start = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        date_range = EventDateRange(start=start, end=end)

        assert date_range.duration == timedelta(hours=2)


@pytest.mark.unit
class TestJournal:
    """Test Journal entity."""

    def test_create_journal_minimal(self):
        """Test creating journal with minimal required fields."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        journal = Journal(
            user_id="test-user-123",
            title="Test Journal",
            content="Test content",
            event_date_range=date_range,
        )

        assert journal.id is None
        assert journal.user_id == "test-user-123"
        assert journal.title == "Test Journal"
        assert journal.content == "Test content"
        assert journal.event_date_range == date_range
        assert journal.parent_id is None
        assert journal.order is None

    def test_create_journal_complete(self):
        """Test creating journal with all fields."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now + timedelta(hours=2))

        journal = Journal(
            id=1,
            user_id="test-user-123",
            title="Complete Journal",
            content="Full content here",
            event_date_range=date_range,
            parent_id=10,
            order=5,
            created_at=now,
            updated_at=now,
        )

        assert journal.id == 1
        assert journal.parent_id == 10
        assert journal.order == 5
        assert journal.created_at == now
        assert journal.updated_at == now

    def test_empty_title_raises_error(self):
        """Test that empty title raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        with pytest.raises(JournalValidationError, match="Title is required"):
            Journal(
                user_id="test-user-123",
                title="",
                content="Content",
                event_date_range=date_range,
            )

    def test_whitespace_title_raises_error(self):
        """Test that whitespace-only title raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        with pytest.raises(JournalValidationError, match="Title is required"):
            Journal(
                user_id="test-user-123",
                title="   ",
                content="Content",
                event_date_range=date_range,
            )

    def test_title_too_long_raises_error(self):
        """Test that title exceeding max length raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)
        long_title = "a" * (MAX_TITLE_LENGTH + 1)

        with pytest.raises(
            JournalValidationError,
            match=f"Title cannot exceed {MAX_TITLE_LENGTH} characters",
        ):
            Journal(
                user_id="test-user-123",
                title=long_title,
                content="Content",
                event_date_range=date_range,
            )

    def test_title_at_max_length_is_valid(self):
        """Test that title at exactly max length is valid."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)
        max_title = "a" * MAX_TITLE_LENGTH

        journal = Journal(
            user_id="test-user-123",
            title=max_title,
            content="Content",
            event_date_range=date_range,
        )

        assert len(journal.title) == MAX_TITLE_LENGTH

    def test_empty_content_raises_error(self):
        """Test that empty content raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        with pytest.raises(JournalValidationError, match="Content is required"):
            Journal(
                user_id="test-user-123",
                title="Title",
                content="",
                event_date_range=date_range,
            )

    def test_whitespace_content_raises_error(self):
        """Test that whitespace-only content raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        with pytest.raises(JournalValidationError, match="Content is required"):
            Journal(
                user_id="test-user-123",
                title="Title",
                content="   \n\t  ",
                event_date_range=date_range,
            )

    def test_empty_user_id_raises_error(self):
        """Test that empty user_id raises error."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        with pytest.raises(JournalValidationError, match="User ID is required"):
            Journal(
                user_id="",
                title="Title",
                content="Content",
                event_date_range=date_range,
            )

    def test_constants_have_expected_values(self):
        """Test that constants are correctly defined."""
        assert MAX_HIERARCHY_DEPTH == 5
        assert MAX_TITLE_LENGTH == 500


@pytest.mark.unit
class TestJournalHierarchy:
    """Test Journal hierarchy-related functionality."""

    def test_journal_with_parent_id(self):
        """Test creating a child journal with parent_id."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        child = Journal(
            user_id="test-user-123",
            title="Child Journal",
            content="Child content",
            event_date_range=date_range,
            parent_id=1,
        )

        assert child.parent_id == 1

    def test_journal_order_field(self):
        """Test journal order field for sibling ordering."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        journal = Journal(
            user_id="test-user-123",
            title="Ordered Journal",
            content="Content",
            event_date_range=date_range,
            order=3,
        )

        assert journal.order == 3

    def test_is_child_property(self):
        """Test is_child property."""
        now = datetime.now(UTC)
        date_range = EventDateRange(start=now, end=now)

        root_journal = Journal(
            user_id="test-user-123",
            title="Root",
            content="Content",
            event_date_range=date_range,
        )

        child_journal = Journal(
            user_id="test-user-123",
            title="Child",
            content="Content",
            event_date_range=date_range,
            parent_id=1,
        )

        assert root_journal.is_child is False
        assert child_journal.is_child is True
