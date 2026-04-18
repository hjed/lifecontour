from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core.journal.services.attended_transition_service import (
    transition_attending_to_attended,
)


@pytest.mark.asyncio
async def test_transition_attending_to_attended_single_batch() -> None:
    """Test when all records fit in a single batch."""
    repo = AsyncMock()
    repo.transition_attending_to_attended.return_value = (
        5  # Returns less than batch size
    )

    now = datetime(2023, 1, 1, tzinfo=UTC)
    result = await transition_attending_to_attended(repo, now=now, batch_size=10)

    assert result.transitioned_count == 5
    assert result.batches_processed == 1
    repo.transition_attending_to_attended.assert_called_once_with(
        before=now, batch_size=10
    )


@pytest.mark.asyncio
async def test_transition_attending_to_attended_multiple_batches() -> None:
    """Test when records span multiple batches."""
    repo = AsyncMock()
    # Batch 1 returns 10 (full), Batch 2 returns 10 (full), Batch 3 returns 3 (partial/done)
    repo.transition_attending_to_attended.side_effect = [10, 10, 3]

    now = datetime(2023, 1, 1, tzinfo=UTC)
    result = await transition_attending_to_attended(repo, now=now, batch_size=10)

    assert result.transitioned_count == 23
    assert result.batches_processed == 3
    assert repo.transition_attending_to_attended.call_count == 3


@pytest.mark.asyncio
async def test_transition_attending_to_attended_max_iterations() -> None:
    """Test safety stop on max iterations."""
    repo = AsyncMock()
    # Always returns full batch, should stop at max_iterations
    repo.transition_attending_to_attended.return_value = 10

    now = datetime(2023, 1, 1, tzinfo=UTC)
    result = await transition_attending_to_attended(
        repo, now=now, batch_size=10, max_iterations=5
    )

    assert result.transitioned_count == 50
    assert result.batches_processed == 5
    assert repo.transition_attending_to_attended.call_count == 5


@pytest.mark.asyncio
async def test_transition_attending_to_attended_no_records() -> None:
    """Test when there are no records to process."""
    repo = AsyncMock()
    repo.transition_attending_to_attended.return_value = 0

    result = await transition_attending_to_attended(repo, batch_size=10)

    assert result.transitioned_count == 0
    assert result.batches_processed == 1
    repo.transition_attending_to_attended.assert_called_once()
