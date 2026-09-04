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
        mock_row.start_time = None
        mock_row.end_time = None
        mock_row.timezone = None
        mock_row.user_timezone = None

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
        mock_row.start_time = None
        mock_row.end_time = None
        mock_row.timezone = None
        mock_row.user_timezone = None
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
                    "start": {"dateTime": "2024-01-01T10:00:00Z"},
                    "end": {"dateTime": "2024-01-01T11:00:00Z"},
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
            mock_row.start_time = None
            mock_row.end_time = None
            mock_row.timezone = None
            mock_row.user_timezone = None
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
            # An event this push put on the old calendar and no inbound sync
            # has ever confirmed — which is what makes it a link the push
            # should prune.
            mock_link_row.external_identity = None
            mock_link_row.sync_capability = "outbound"
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


class TestProcessJournalEventTimezones:
    """Outbound push reads the stored instants in the event's timezone.

    Journal date-range bounds are UTC instants of local midnight. Sydney
    (UTC+10) local midnight on 5 Sept is 14:00 UTC on 4 Sept, so an outbound
    push that reads the UTC date sends the event a day early.
    """

    SYDNEY_MIDNIGHT_5_SEPT = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)

    @staticmethod
    def _session_factory(**row_overrides):
        mock_row = MagicMock()
        mock_row.journal_id = 1
        mock_row.title = "Birthday"
        mock_row.content = "Content"
        mock_row.event_date_range_start = (
            TestProcessJournalEventTimezones.SYDNEY_MIDNIGHT_5_SEPT
        )
        mock_row.event_date_range_end = (
            TestProcessJournalEventTimezones.SYDNEY_MIDNIGHT_5_SEPT
        )
        mock_row.user_id = 1
        mock_row.is_all_day = True
        mock_row.start_time = None
        mock_row.end_time = None
        mock_row.timezone = None
        mock_row.user_timezone = None
        mock_row.location = None
        mock_row.calendar_id = "test-cal-id"
        mock_row.google_calendar_id = "test-google-cal-id"
        mock_row.is_synced_to_google = True
        mock_row.access_role = "owner"
        mock_row.external_event_id = None
        mock_row.sync_status = None
        mock_row.private_description = False
        for name, value in row_overrides.items():
            setattr(mock_row, name, value)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_auth_row = MagicMock()
        mock_auth_row.google_account_email = "test@example.com"
        mock_auth_result = MagicMock()
        mock_auth_result.fetchone.return_value = mock_auth_row

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [mock_result, mock_auth_result] + [
            MagicMock() for _ in range(10)
        ]

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        return mock_factory

    @staticmethod
    async def _push(session_factory) -> dict:
        from worker import process_journal_event

        mock_client = AsyncMock()
        mock_client.create_event.return_value = {"id": "new_event_id", "etag": "e"}

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type="JournalCreated",
                event_data={"journal_id": 1},
            )

        assert result["status"] == "success"
        mock_client.create_event.assert_called_once()
        return mock_client.create_event.call_args[0][0]

    @pytest.mark.asyncio
    async def test_all_day_event_uses_the_users_configured_timezone(self):
        payload = await self._push(
            self._session_factory(user_timezone="Australia/Sydney")
        )

        assert payload["start"] == {"date": "2026-09-05"}
        assert payload["end"] == {"date": "2026-09-06"}

    @pytest.mark.asyncio
    async def test_the_events_own_timezone_wins_over_the_users(self):
        # 12:00 UTC on 4 Sept is midnight on 5 Sept in Auckland (UTC+12) but
        # still 4 Sept in Los Angeles.
        payload = await self._push(
            self._session_factory(
                event_date_range_start=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                event_date_range_end=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
                timezone="Pacific/Auckland",
                user_timezone="America/Los_Angeles",
            )
        )

        assert payload["start"] == {"date": "2026-09-05"}
        assert payload["end"] == {"date": "2026-09-06"}

    @pytest.mark.asyncio
    async def test_no_timezone_anywhere_falls_back_to_the_utc_date(self):
        payload = await self._push(self._session_factory())

        assert payload["start"] == {"date": "2026-09-04"}
        assert payload["end"] == {"date": "2026-09-05"}

    @pytest.mark.asyncio
    async def test_timed_event_anchors_clock_times_in_the_users_timezone(self):
        from datetime import time

        payload = await self._push(
            self._session_factory(
                is_all_day=False,
                start_time=time(9, 0),
                end_time=time(10, 0),
                user_timezone="Australia/Sydney",
            )
        )

        assert payload["start"] == {
            "dateTime": "2026-09-04T23:00:00Z",
            "timeZone": "Australia/Sydney",
        }
        assert payload["end"] == {
            "dateTime": "2026-09-05T00:00:00Z",
            "timeZone": "Australia/Sydney",
        }
