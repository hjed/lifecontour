"""Tests for process_journal_event task."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProcessJournalEvent:
    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for database operations."""
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.journal_id = 1
        mock_row.title = "Test Journal"
        mock_row.content = "Content"
        mock_row.event_date_range_start = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        mock_row.event_date_range_end = datetime(2024, 1, 1, 11, 0, tzinfo=UTC)
        mock_row.user_id = 1
        mock_row.is_all_day = False
        mock_row.location = "Test Location"
        mock_row.calendar_id = "test-cal-id"
        mock_row.google_calendar_id = "test-google-cal-id"
        mock_row.is_synced_to_google = True
        mock_row.external_event_id = None
        mock_row.sync_status = None
        mock_row.private_description = False

        mock_result.fetchone.return_value = mock_row

        mock_auth_result = MagicMock()
        mock_auth_row = MagicMock()
        mock_auth_row.google_account_email = "test@example.com"
        mock_auth_result.fetchone.return_value = mock_auth_row

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [mock_result, mock_auth_result] + [
            MagicMock() for _ in range(10)
        ]

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
        mock_client.create_event.return_value = {
            "id": "new_event_id",
            "etag": "new_etag",
        }
        mock_client.update_event.return_value = {
            "id": "existing_event_id",
            "etag": "new_etag",
        }
        return mock_client

    @pytest.mark.asyncio
    async def test_process_journal_event_creates_new(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        from worker import process_journal_event

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_journal_event(
                ctx=ctx, event_type="JournalCreated", event_data={"journal_id": 1}
            )

            assert result["status"] == "success"
            assert result["action"] == "create"
            assert result["external_event_id"] == "new_event_id"

            # Verify API was called with correct payload
            mock_google_client.create_event.assert_called_once()
            call_args = mock_google_client.create_event.call_args[0][0]
            assert call_args["summary"] == "Test Journal"
            assert "start" in call_args
            assert "end" in call_args

    @pytest.mark.asyncio
    async def test_process_journal_event_updates_existing(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        mock_session = mock_session_factory.return_value.__aenter__.return_value

        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.journal_id = 1
        mock_row.title = "Test Journal"
        mock_row.content = "Content"
        mock_row.event_date_range_start = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        mock_row.event_date_range_end = datetime(2024, 1, 1, 11, 0, tzinfo=UTC)
        mock_row.user_id = 1
        mock_row.is_all_day = False
        mock_row.location = "Test Location"
        mock_row.calendar_id = "test-cal-id"
        mock_row.google_calendar_id = "test-google-cal-id"
        mock_row.is_synced_to_google = True
        mock_row.external_event_id = "existing_event_id"
        mock_row.sync_status = "synced"
        mock_row.private_description = False
        mock_result.fetchone.return_value = mock_row

        mock_auth_result = MagicMock()
        mock_auth_row = MagicMock()
        mock_auth_row.google_account_email = "test@example.com"
        mock_auth_result.fetchone.return_value = mock_auth_row

        mock_session.execute.side_effect = [mock_result, mock_auth_result] + [
            MagicMock() for _ in range(10)
        ]

        from worker import process_journal_event

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalUpdated",
                event_data={
                    "journal_id": 1,
                    "changed_fields": {"title": ("Old", "New")},
                },
            )

            assert result["status"] == "success"
            assert result["action"] == "update"
            assert result["external_event_id"] == "existing_event_id"

            # Verify API was called
            mock_google_client.update_event.assert_called_once_with(
                "existing_event_id",
                {
                    "summary": "Test Journal",
                    "description": "Content",
                    "location": "Test Location",
                    "start": {"dateTime": "2024-01-01T10:00:00+00:00"},
                    "end": {"dateTime": "2024-01-01T11:00:00+00:00"},
                },
                calendar_id="test-google-cal-id",
            )

    @pytest.mark.asyncio
    async def test_process_journal_event_ignores_not_found(self, mock_session_factory):
        mock_session = mock_session_factory.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.side_effect = [mock_result] + [
            MagicMock() for _ in range(10)
        ]

        from worker import process_journal_event

        ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
        result = await process_journal_event(
            ctx=ctx, event_type="JournalCreated", event_data={"journal_id": 1}
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "journal_not_found"

    @pytest.mark.asyncio
    async def test_process_journal_event_ignores_no_op_update(
        self, mock_session_factory
    ):
        from worker import process_journal_event

        ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
        result = await process_journal_event(
            ctx=ctx,
            event_type="JournalUpdated",
            event_data={
                "journal_id": 1,
                "changed_fields": {"tags": ([], ["new_tag"])},  # Non-sync field
            },
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "no_op_update"

    @pytest.mark.asyncio
    async def test_process_journal_event_deletes_existing(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        from worker import process_journal_event

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            mock_session = mock_session_factory.return_value.__aenter__.return_value
            mock_session.execute.side_effect = None
            mock_result = MagicMock()
            mock_row = MagicMock()
            mock_row.google_account_email = "test@example.com"
            mock_result.fetchone.return_value = mock_row
            mock_session.execute.return_value = mock_result

            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 1,
                    "user_id": "test_user",
                    "external_identifiers": {"google": ["existing_event_id"]},
                },
            )

            assert result["status"] == "success"
            assert result["action"] == "delete"
            assert result["external_event_ids"] == ["existing_event_id"]

            # Verify auth layout query was executed
            assert mock_session.execute.call_count == 1
            auth_call_args = mock_session.execute.call_args[0]
            assert "SELECT google_account_email" in str(auth_call_args[0])

            # Verify API was called with fallback calendar_id 'primary' for old string format
            mock_google_client.delete_event.assert_called_once_with(
                "existing_event_id", "primary"
            )

    @pytest.mark.asyncio
    async def test_process_journal_event_ignores_delete_if_no_identifier(
        self, mock_session_factory
    ):
        from worker import process_journal_event

        ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
        result = await process_journal_event(
            ctx=ctx,
            event_type="JournalDeleted",
            event_data={
                "journal_id": 1,
                "user_id": "test_user",
                "external_identifiers": {},
            },
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "no_external_id_for_provider"

    @pytest.mark.asyncio
    async def test_process_journal_event_orphan_delete_fails(
        self, mock_session_factory, mock_google_auth_service, mock_google_client
    ):
        from googleapiclient.errors import HttpError

        from worker import process_journal_event

        mock_google_client.delete_event.side_effect = HttpError(
            resp=MagicMock(status=500, reason="Internal Server Error"),
            content=b"Internal Server Error",
        )

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            mock_session = mock_session_factory.return_value.__aenter__.return_value
            mock_result = MagicMock()
            mock_row = MagicMock()
            mock_row.journal_id = 1
            mock_row.title = "Test Journal"
            mock_row.content = "Content"
            mock_row.event_date_range_start = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
            mock_row.event_date_range_end = datetime(2024, 1, 1, 11, 0, tzinfo=UTC)
            mock_row.user_id = 1
            mock_row.is_all_day = False
            mock_row.location = "Test Location"
            mock_row.calendar_id = "test-cal-id-new"
            mock_row.google_calendar_id = "test-google-cal-id-new"
            mock_row.is_synced_to_google = True
            mock_row.external_event_id = "new_event_id"
            mock_row.sync_status = "synced"
            mock_row.private_description = False
            mock_result.fetchone.return_value = mock_row

            mock_auth_result = MagicMock()
            mock_auth_row = MagicMock()
            mock_auth_row.google_account_email = "test@example.com"
            mock_auth_result.fetchone.return_value = mock_auth_row

            mock_links_result = MagicMock()
            mock_link_row = MagicMock()
            mock_link_row.calendar_id = "test-cal-id-old"
            mock_link_row.external_event_id = "old_event_id"
            mock_link_row.google_calendar_id = "test-google-cal-id-old"
            mock_links_result.fetchall.return_value = [mock_link_row]

            mock_session.execute.side_effect = [
                mock_result,  # SELECT journal...
                mock_auth_result,  # SELECT google_account_email
                mock_links_result,  # SELECT existing links
            ] + [MagicMock() for _ in range(15)]

            ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalUpdated",
                event_data={
                    "journal_id": 1,
                    "changed_fields": {"calendar_info": ("Old", "New")},
                },
            )

            assert result["status"] == "success"
            mock_google_client.delete_event.assert_called_once_with(
                "old_event_id", "test-google-cal-id-old"
            )

            # Should have called the UPDATE statement setting status to errored
            update_call = None
            for call in mock_session.execute.call_args_list:
                stmt_str = str(call[0][0])
                if (
                    "UPDATE journal_external_event_links" in stmt_str
                    and "sync_status = 'errored'" in stmt_str
                ):
                    update_call = call
                    break

            assert update_call is not None, (
                "Did not execute UPDATE journal_external_event_links to set errored state"
            )
            assert update_call[0][1]["calendar_id"] == "test-cal-id-old"
