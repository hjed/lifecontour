"""Tests for process_tag_event task."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProcessTagEvent:
    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for database operations."""
        mock_auth_result = MagicMock()
        mock_auth_row = MagicMock()
        mock_auth_row.google_account_email = "test@example.com"
        mock_auth_row.user_id = 1
        mock_auth_result.fetchall.return_value = [mock_auth_row]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_auth_result

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        return mock_factory

    @pytest.fixture
    def mock_google_auth_service(self):
        mock_service = AsyncMock()
        mock_service.get_access_token.return_value = "mock_access_token"
        return mock_service

    @pytest.fixture
    def mock_google_client(self):
        mock_client = AsyncMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_process_tag_event_updated(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        from worker import process_tag_event

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
            patch(
                "worker._build_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/123": "Work/Project"},
            ),
        ):
            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_tag_event(
                ctx=ctx,
                event_type="TagUpdated",
                event_data={
                    "changed_fields": {"full_path": ("Work/Project", "Work/Project2")},
                },
            )

            assert result["status"] == "success"
            assert result["processed_users"] == 1
            mock_google_client.update_contact_group.assert_called_once_with(
                "contactGroups/123", "Work/Project2"
            )

    @pytest.mark.asyncio
    async def test_process_tag_event_deleted(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        from worker import process_tag_event

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
            patch(
                "worker._build_contact_group_mapping",
                new_callable=AsyncMock,
                return_value={"contactGroups/456": "To_Delete"},
            ),
        ):
            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_tag_event(
                ctx=ctx,
                event_type="TagDeleted",
                event_data={
                    "tag_id": 1,
                    "tag_name": "To_Delete",
                },
            )

            assert result["status"] == "success"
            assert result["processed_users"] == 1
            mock_google_client.delete_contact_group.assert_called_once_with(
                "contactGroups/456"
            )
