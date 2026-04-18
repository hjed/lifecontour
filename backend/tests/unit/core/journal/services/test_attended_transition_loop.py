"""
Unit tests for the attended transition background loop.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.core.journal.services.attended_transition_loop import (
    run_attended_transition_loop,
)
from app.core.journal.services.attended_transition_service import TransitionResult


@pytest.mark.asyncio
async def test_run_attended_transition_loop_success():
    """Test the loop processes items and sleeps, handling cancellation correctly."""

    # Setup mocks
    mock_repo = AsyncMock(spec=JournalContactRelationshipRepository)

    # We mock transition_attending_to_attended by patching it
    # But it's easier to patch it in the test using monkeypatch

    # Actually, we can use a mock container
    # The container should return a request_container context manager
    mock_request_container = AsyncMock()
    mock_request_container.get.return_value = mock_repo

    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_request_container

    mock_container = MagicMock()
    mock_container.return_value = mock_context_manager

    # We'll need to mock asyncio.sleep to raise CancelledError so the loop terminates
    sleep_mock = AsyncMock()
    sleep_mock.side_effect = [None, asyncio.CancelledError()]

    # We'll mock the transition_service function
    transition_mock = AsyncMock(
        return_value=TransitionResult(transitioned_count=5, batches_processed=1)
    )

    import app.core.journal.services.attended_transition_loop as loop_module

    # Run the loop
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "sleep", sleep_mock)
        mp.setattr(loop_module, "transition_attending_to_attended", transition_mock)

        # It should exit after the second sleep due to CancelledError
        await run_attended_transition_loop(mock_container, interval_seconds=3600)

    # Verify expectations
    assert mock_container.call_count == 2
    assert mock_request_container.get.call_count == 2
    mock_request_container.get.assert_called_with(JournalContactRelationshipRepository)

    assert transition_mock.call_count == 2
    transition_mock.assert_called_with(mock_repo)

    assert sleep_mock.call_count == 2
    sleep_mock.assert_called_with(3600)


@pytest.mark.asyncio
async def test_run_attended_transition_loop_exception_recovery():
    """Test the loop continues running if an exception occurs during processing."""

    mock_request_container = AsyncMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_request_container

    mock_container = MagicMock()
    mock_container.return_value = mock_context_manager

    sleep_mock = AsyncMock()
    sleep_mock.side_effect = [None, asyncio.CancelledError()]

    transition_mock = AsyncMock()
    # First call raises an exception, second call succeeds
    transition_mock.side_effect = [
        Exception("Test error"),
        TransitionResult(transitioned_count=5, batches_processed=1),
    ]

    import app.core.journal.services.attended_transition_loop as loop_module

    # Run the loop
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "sleep", sleep_mock)
        mp.setattr(loop_module, "transition_attending_to_attended", transition_mock)

        # Should not raise the internal exception, but swallow it and continue
        await run_attended_transition_loop(mock_container, interval_seconds=3600)

    # Verify the loop still tried to sleep after the exception and processed the next iteration
    assert transition_mock.call_count == 2
    assert sleep_mock.call_count == 2
