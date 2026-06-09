"""Unit tests for ContactSummaryService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import ContactSummary, SummaryStatus
from core_shared.models.contacts.exceptions import ContactValidationError

from app.api.contacts.schemas import ContactSummaryUpdateData
from app.core.contacts.models.events import ContactSummaryRefreshRequested
from app.core.contacts.services.contact_summary_service import ContactSummaryService


@pytest.fixture
def mock_summary_repo():
    """Create a mock contact summary repository."""
    repo = AsyncMock()
    # upsert echoes back the summary it was given by default
    repo.upsert.side_effect = lambda summary: summary
    return repo


@pytest.fixture
def mock_event_publisher():
    """Create a mock contact event publisher."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock transaction (not a real AsyncConnection)."""
    return AsyncMock()


@pytest.fixture
def summary_service(mock_summary_repo, mock_event_publisher):
    """Create a ContactSummaryService instance."""
    return ContactSummaryService(
        summary_repo=mock_summary_repo,
        event_publisher=mock_event_publisher,
    )


class TestRequestRefresh:
    """Test the request_refresh unit of work."""

    @pytest.mark.asyncio
    async def test_creates_pending_summary_when_none_exists(
        self, summary_service, mock_summary_repo, mock_event_publisher, mock_transaction
    ):
        """With no existing summary, a pending one is upserted and an event fires."""
        mock_summary_repo.find_by_contact_id.return_value = None

        await summary_service.request_refresh(42, transaction=mock_transaction)

        mock_summary_repo.upsert.assert_called_once()
        upserted = mock_summary_repo.upsert.call_args.args[0]
        assert upserted.contact_id == 42
        assert upserted.status == SummaryStatus.PENDING
        mock_summary_repo.update_status.assert_not_called()

        mock_event_publisher.publish.assert_called_once()
        event = mock_event_publisher.publish.call_args.args[0]
        assert isinstance(event, ContactSummaryRefreshRequested)
        assert event.aggregate_id == 42
        assert event.event_data == {"contact_id": 42}

    @pytest.mark.asyncio
    async def test_sets_status_pending_when_summary_exists(
        self, summary_service, mock_summary_repo, mock_event_publisher, mock_transaction
    ):
        """An existing (enabled) summary has its status set to pending."""
        mock_summary_repo.find_by_contact_id.return_value = ContactSummary(
            contact_id=42, status=SummaryStatus.GENERATED
        )

        await summary_service.request_refresh(42, transaction=mock_transaction)

        mock_summary_repo.update_status.assert_called_once_with(
            42, SummaryStatus.PENDING.value
        )
        mock_summary_repo.upsert.assert_not_called()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_disabled(
        self, summary_service, mock_summary_repo, mock_event_publisher, mock_transaction
    ):
        """A disabled summary blocks refresh with a validation error, no event."""
        mock_summary_repo.find_by_contact_id.return_value = ContactSummary(
            contact_id=42, status=SummaryStatus.DISABLED, is_disabled=True
        )

        with pytest.raises(ContactValidationError):
            await summary_service.request_refresh(42, transaction=mock_transaction)

        mock_summary_repo.update_status.assert_not_called()
        mock_summary_repo.upsert.assert_not_called()
        mock_event_publisher.publish.assert_not_called()


class TestUpdateSummary:
    """Test the update_summary unit of work."""

    @pytest.mark.asyncio
    async def test_disable_sets_disabled_status(
        self, summary_service, mock_summary_repo, mock_transaction
    ):
        """Disabling marks the summary disabled and sets DISABLED status."""
        mock_summary_repo.find_by_contact_id.return_value = ContactSummary(
            contact_id=7, status=SummaryStatus.GENERATED
        )
        update_data = ContactSummaryUpdateData(is_disabled=True)

        result = await summary_service.update_summary(
            7, update_data, transaction=mock_transaction
        )

        assert result.is_disabled is True
        assert result.status == SummaryStatus.DISABLED
        mock_summary_repo.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_override_text_sets_generated(
        self, summary_service, mock_summary_repo, mock_transaction
    ):
        """Setting override text flags user override and GENERATED status."""
        mock_summary_repo.find_by_contact_id.return_value = ContactSummary(
            contact_id=7, status=SummaryStatus.PENDING
        )
        update_data = ContactSummaryUpdateData(user_override_text="Custom summary")

        result = await summary_service.update_summary(
            7, update_data, transaction=mock_transaction
        )

        assert result.is_user_override is True
        assert result.user_override_text == "Custom summary"
        assert result.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_clearing_override_text_resets_to_pending(
        self, summary_service, mock_summary_repo, mock_transaction
    ):
        """Explicitly clearing override text with no AI text resets to pending."""
        mock_summary_repo.find_by_contact_id.return_value = ContactSummary(
            contact_id=7,
            status=SummaryStatus.GENERATED,
            is_user_override=True,
            user_override_text="Old override",
        )
        # Explicitly set user_override_text to None so it is in model_fields_set.
        update_data = ContactSummaryUpdateData(user_override_text=None)

        result = await summary_service.update_summary(
            7, update_data, transaction=mock_transaction
        )

        assert result.is_user_override is False
        assert result.user_override_text is None
        assert result.status == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_creates_summary_when_none_exists(
        self, summary_service, mock_summary_repo, mock_transaction
    ):
        """With no existing summary, a new one is created and upserted."""
        mock_summary_repo.find_by_contact_id.return_value = None
        update_data = ContactSummaryUpdateData(is_disabled=True)

        result = await summary_service.update_summary(
            99, update_data, transaction=mock_transaction
        )

        assert result.contact_id == 99
        assert result.is_disabled is True
        assert result.status == SummaryStatus.DISABLED
        mock_summary_repo.upsert.assert_called_once()
