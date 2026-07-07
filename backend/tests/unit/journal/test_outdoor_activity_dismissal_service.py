"""Unit tests for OutdoorActivityDismissalService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import OutdoorActivityDismissal

from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)


@pytest.fixture
def mock_dismissal_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_transaction() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def dismissal_service(
    mock_dismissal_repo: AsyncMock,
) -> OutdoorActivityDismissalService:
    return OutdoorActivityDismissalService(dismissal_repo=mock_dismissal_repo)


class TestDismiss:
    @pytest.mark.asyncio
    async def test_dismiss_delegates_to_repo(
        self,
        dismissal_service: OutdoorActivityDismissalService,
        mock_dismissal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        expected = OutdoorActivityDismissal(
            journal_id=10, user_id="user-1", provenance=Provenance.UI
        )
        mock_dismissal_repo.dismiss.return_value = expected

        result = await dismissal_service.dismiss(
            journal_id=10,
            user_id="user-1",
            provenance=Provenance.UI,
            transaction=mock_transaction,
        )

        assert result is expected
        mock_dismissal_repo.dismiss.assert_awaited_once_with(
            journal_id=10, user_id="user-1", provenance=Provenance.UI
        )

    @pytest.mark.asyncio
    async def test_dismiss_passes_provenance_through(
        self,
        dismissal_service: OutdoorActivityDismissalService,
        mock_dismissal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The service records whatever provenance it is given (UI vs MCP)."""
        mock_dismissal_repo.dismiss.return_value = OutdoorActivityDismissal(
            journal_id=20, user_id="user-1", provenance=Provenance.MCP
        )

        await dismissal_service.dismiss(
            journal_id=20,
            user_id="user-1",
            provenance=Provenance.MCP,
            transaction=mock_transaction,
        )

        mock_dismissal_repo.dismiss.assert_awaited_once_with(
            journal_id=20, user_id="user-1", provenance=Provenance.MCP
        )


class TestUndismiss:
    @pytest.mark.asyncio
    async def test_undismiss_delegates_to_repo(
        self,
        dismissal_service: OutdoorActivityDismissalService,
        mock_dismissal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_dismissal_repo.undismiss.return_value = True

        result = await dismissal_service.undismiss(
            journal_id=10, user_id="user-1", transaction=mock_transaction
        )

        assert result is True
        mock_dismissal_repo.undismiss.assert_awaited_once_with(
            journal_id=10, user_id="user-1"
        )

    @pytest.mark.asyncio
    async def test_undismiss_returns_false_when_not_dismissed(
        self,
        dismissal_service: OutdoorActivityDismissalService,
        mock_dismissal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_dismissal_repo.undismiss.return_value = False

        result = await dismissal_service.undismiss(
            journal_id=99, user_id="user-1", transaction=mock_transaction
        )

        assert result is False
        mock_dismissal_repo.undismiss.assert_awaited_once_with(
            journal_id=99, user_id="user-1"
        )
