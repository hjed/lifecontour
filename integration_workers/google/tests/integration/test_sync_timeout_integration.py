"""Integration tests for worker execution options."""

from unittest.mock import AsyncMock, patch

import pytest

from worker import sync_google_contacts


@pytest.mark.asyncio
async def test_sync_google_accepts_job_timeout():
    """Test that sync_google_contacts can be called with a _job_timeout kwarg, as passed by arq."""

    mock_session_factory = AsyncMock()
    mock_auth_service = AsyncMock()
    mock_contacts_client = AsyncMock()

    with (
        patch("worker.GoogleAuthService", return_value=mock_auth_service),
        patch("worker.GoogleAPIClient", return_value=mock_contacts_client),
    ):
        # This simulates how ARQ might call the function, passing job metadata as kwargs
        # Specifically, we want to ensure it doesn't fail with TypeError for unexpected kwargs
        try:
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory, "job_id": "test_job_123"},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
                _job_timeout=300,  # This reproduces the issue
            )
            assert result is not None
        except TypeError as e:
            if "_job_timeout" in str(e):
                pytest.fail(
                    f"sync_google_contacts failed to accept _job_timeout kwarg: {e}"
                )
            raise
