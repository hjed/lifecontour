"""Tests for process_journal_event task."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SYDNEY_MIDNIGHT_5_SEPT = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)


def _push_session_factory(**row_overrides: Any) -> MagicMock:
    """A session factory whose first two reads answer the outbound push.

    The push opens one session and runs a fixed opening pair of queries — the
    journal-with-calendar join, then the Google account lookup — so a factory
    that answers those two and returns bare mocks thereafter is enough to
    drive it. ``row_overrides`` set the journal row's columns.
    """
    mock_row = MagicMock()
    mock_row.journal_id = 1
    mock_row.title = "Birthday"
    mock_row.content = "Content"
    mock_row.event_date_range_start = SYDNEY_MIDNIGHT_5_SEPT
    mock_row.event_date_range_end = SYDNEY_MIDNIGHT_5_SEPT
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


def _forbidden_body(*reasons: str) -> bytes:
    """A 403 body naming the given reason codes, as Google sends it."""
    errors = ", ".join(
        f'{{"domain": "global", "reason": "{reason}", "message": "Forbidden"}}'
        for reason in reasons
    )
    return f'{{"error": {{"code": 403, "errors": [{errors}]}}}}'.encode()


@contextmanager
def _google_account(
    mock_session_factory: MagicMock,
    mock_google_auth_service: MagicMock,
    mock_google_client: MagicMock,
) -> Iterator[MagicMock]:
    """Patch in a user with a Google account, ready for the worker to act as.

    Every deletion test needs the same arrangement — the auth row the handler
    reads before it builds a client — and only what the event carries differs.
    """
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
        yield mock_session


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

        with _google_account(
            mock_session_factory, mock_google_auth_service, mock_google_client
        ) as mock_session:
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

            # The deletion reads twice before calling Google: whose account to
            # act as, and which of their calendars refuse writes.
            statements = [
                str(call[0][0]) for call in mock_session.execute.call_args_list
            ]
            assert len(statements) == 2
            assert "SELECT google_account_email" in statements[0]
            assert "access_role" in statements[1]

            # Verify API was called with fallback calendar_id 'primary' for old string format
            mock_google_client.delete_event.assert_called_once_with(
                "existing_event_id", "primary"
            )

    @pytest.mark.asyncio
    async def test_delete_reads_the_calendar_the_identifier_names(
        self,
        mock_session_factory: MagicMock,
        mock_google_auth_service: MagicMock,
        mock_google_client: MagicMock,
    ) -> None:
        """The per-source payload deletes from the calendar the link hung off.

        ``JournalDeleted`` now files each identifier under the integration that
        owns its calendar, so the Google key holds Google's own entries and
        nothing else. This pins that the reader still finds them.
        """
        from worker import process_journal_event

        with _google_account(
            mock_session_factory, mock_google_auth_service, mock_google_client
        ):
            result = await process_journal_event(
                ctx={"session_factory": mock_session_factory, "job_id": "job123"},
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 1,
                    "user_id": "test_user",
                    "external_identifiers": {
                        "google": [
                            {
                                "external_event_id": "existing_event_id",
                                "calendar_id": "11111111-1111-5111-8111-111111111111",
                                "google_calendar_id": "work@group.calendar.google.com",
                            }
                        ]
                    },
                },
            )

            assert result["status"] == "success"
            mock_google_client.delete_event.assert_called_once_with(
                "existing_event_id", "work@group.calendar.google.com"
            )

    @pytest.mark.asyncio
    async def test_delete_ignores_another_integrations_identifiers(
        self, mock_session_factory: MagicMock
    ) -> None:
        """Only Google's key is Google's work.

        Before the identifiers were filed by source, a Snipe-IT maintenance id
        arrived here with no ``google_calendar_id``, was read as the user's
        primary calendar, and became a delete issued against Google for a
        record Google never had.
        """
        from worker import process_journal_event

        ctx = {"session_factory": mock_session_factory, "job_id": "job123"}
        result = await process_journal_event(
            ctx=ctx,
            event_type="JournalDeleted",
            event_data={
                "journal_id": 1,
                "user_id": "test_user",
                "external_identifiers": {
                    "snipeit_maintenance": [
                        {
                            "external_event_id": "snipeit_maint:17",
                            "calendar_id": "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a",
                            "google_calendar_id": None,
                        }
                    ]
                },
            },
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "no_external_id_for_provider"

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

            # The old calendar's link records that its event is still there
            errored = [
                call
                for call in mock_session.execute.call_args_list
                if "journal_external_event_links" in str(call[0][0])
                and len(call[0]) > 1
                and call[0][1].get("status") == "errored"
            ]

            assert errored, "Did not mark the orphaned link errored"
            assert errored[0][0][1]["calendar_id"] == "test-cal-id-old"


class TestProcessJournalEventTimezones:
    """Outbound push reads the stored instants in the event's timezone.

    Journal date-range bounds are UTC instants of local midnight. Sydney
    (UTC+10) local midnight on 5 Sept is 14:00 UTC on 4 Sept, so an outbound
    push that reads the UTC date sends the event a day early.
    """

    _session_factory = staticmethod(_push_session_factory)

    @staticmethod
    async def _push(session_factory: MagicMock) -> dict[str, Any]:
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
    async def test_timed_event_anchors_clock_times_in_its_own_timezone(self):
        from datetime import time

        payload = await self._push(
            self._session_factory(
                is_all_day=False,
                start_time=time(9, 0),
                end_time=time(10, 0),
                timezone="Australia/Sydney",
                user_timezone="America/Los_Angeles",
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

    @pytest.mark.asyncio
    async def test_timed_event_without_its_own_timezone_pushes_the_stored_instants(
        self,
    ):
        """An imported event's clock times are local to the Google event's zone,
        which the row does not record, so the user's zone must not re-anchor
        them; the stored instants are the truth."""
        from datetime import time

        payload = await self._push(
            self._session_factory(
                is_all_day=False,
                event_date_range_start=datetime(2026, 9, 4, 16, 0, tzinfo=UTC),
                event_date_range_end=datetime(2026, 9, 4, 17, 0, tzinfo=UTC),
                start_time=time(9, 0),
                end_time=time(10, 0),
                timezone=None,
                user_timezone="Australia/Sydney",
            )
        )

        assert payload["start"] == {"dateTime": "2026-09-04T16:00:00Z"}
        assert payload["end"] == {"dateTime": "2026-09-04T17:00:00Z"}


class TestProcessJournalEventInboundEcho:
    """A journal the Google inbound sync applied is not pushed back to Google.

    The inbound sync creates the journal *and* its external event link in one
    transaction, so by the time the resulting JournalCreated reaches this
    worker the link already exists and the push would PATCH the very event the
    journal was built from. Besides being a wasted round trip, Google rejects
    it outright for event types it owns — a contact-linked birthday among them.
    """

    INBOUND = {"source": "google_calendar"}

    @staticmethod
    async def _run(
        event_type: str, event_data: dict[str, Any]
    ) -> tuple[dict[str, Any], AsyncMock]:
        from worker import process_journal_event

        session_factory = _push_session_factory(external_event_id="existing_event_id")
        mock_client = AsyncMock()

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type=event_type,
                event_data=event_data,
            )
        return result, mock_client

    @pytest.mark.asyncio
    async def test_created_by_inbound_sync_is_not_pushed_back(self) -> None:
        result, mock_client = await self._run(
            "JournalCreated", {"journal_id": 1, **self.INBOUND}
        )

        assert result == {"status": "ignored", "reason": "inbound_sync_echo"}
        mock_client.create_event.assert_not_called()
        mock_client.update_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_updated_by_inbound_sync_is_not_pushed_back(self) -> None:
        result, mock_client = await self._run(
            "JournalUpdated",
            {
                "journal_id": 1,
                "changed_fields": {"title": ("Old", "New")},
                **self.INBOUND,
            },
        )

        assert result == {"status": "ignored", "reason": "inbound_sync_echo"}
        mock_client.update_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_locally_sourced_event_is_still_pushed(self) -> None:
        """The guard reads the source, not the journal: a user's own edit to a
        journal that arrived from Google must still reach Google."""
        result, mock_client = await self._run(
            "JournalUpdated",
            {
                "journal_id": 1,
                "changed_fields": {"title": ("Old", "New")},
                "source": "ui",
            },
        )

        assert result["status"] == "success"
        mock_client.update_event.assert_called_once()


class TestProcessJournalEventRestrictedType:
    """Google declining to be written to is a skip, not a failure.

    A birthday or from-Gmail event is derived by Google and accepts almost no
    change. Raising would leave the stream message unacknowledged and retry it
    to the dead-letter path, so the rejection is recorded on the link and the
    event is acknowledged.
    """

    @staticmethod
    async def _push_failing_with(
        error: Exception,
    ) -> tuple[dict[str, Any], AsyncMock]:
        from worker import process_journal_event

        session_factory = _push_session_factory(external_event_id="existing_event_id")
        mock_session = session_factory.return_value.__aenter__.return_value
        mock_client = AsyncMock()
        mock_client.update_event.side_effect = error

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type="JournalUpdated",
                event_data={
                    "journal_id": 1,
                    "changed_fields": {"title": ("Old", "New")},
                    "source": "ui",
                },
            )
        return result, mock_session

    @staticmethod
    def _errored_link_writes(mock_session: AsyncMock) -> list[Any]:
        return [
            call
            for call in mock_session.execute.call_args_list
            if "journal_external_event_links" in str(call[0][0])
            and len(call[0]) > 1
            and call[0][1].get("status") == "errored"
        ]

    @pytest.mark.asyncio
    async def test_restriction_is_a_permanent_skip(
        self, event_type_restriction_error
    ) -> None:
        result, _ = await self._push_failing_with(event_type_restriction_error)

        assert result["status"] == "ignored"
        assert result["reason"] == "event_type_not_modifiable"

    @pytest.mark.asyncio
    async def test_restriction_records_the_divergence_on_the_link(
        self, event_type_restriction_error
    ) -> None:
        """The journal and Google now differ, and the link is where that shows."""
        _, mock_session = await self._push_failing_with(event_type_restriction_error)

        assert self._errored_link_writes(mock_session)

    @pytest.mark.asyncio
    async def test_other_http_errors_still_raise(self, google_http_error) -> None:
        """A transient fault must keep retrying, so only the restriction is caught."""
        from googleapiclient.errors import HttpError

        error = google_http_error(500, b'{"error": {"code": 500}}')

        with pytest.raises(HttpError):
            await self._push_failing_with(error)


class TestOutboundPushPermissions:
    """Outbound push against a calendar the account may not write to.

    Pushing to a calendar shared read-only is refused by Google every time,
    so the stored access role is what has to stop the push before it is made.
    """

    @staticmethod
    def _client() -> AsyncMock:
        mock_client = AsyncMock()
        mock_client.create_event.return_value = {"id": "new_event_id", "etag": "e"}
        mock_client.update_event.return_value = {"id": "existing_event_id", "etag": "e"}
        mock_client.list_calendars.return_value = {"items": []}
        return mock_client

    @staticmethod
    async def _push(
        session_factory: MagicMock,
        client: AsyncMock,
        event_type: str = "JournalUpdated",
    ) -> dict[str, Any]:
        from worker import process_journal_event

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=client),
        ):
            return await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type=event_type,
                event_data={
                    "journal_id": 1,
                    "changed_fields": {"title": ("Old", "New")},
                },
            )

    @pytest.mark.asyncio
    async def test_read_only_calendar_is_not_pushed_to(self) -> None:
        session_factory = _push_session_factory(
            access_role="reader", external_event_id="existing_event_id"
        )
        client = self._client()

        result = await self._push(session_factory, client)

        assert result["status"] == "ignored"
        assert result["reason"] == "read_only_calendar"
        client.update_event.assert_not_called()
        client.create_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_free_busy_calendar_is_not_pushed_to(self) -> None:
        session_factory = _push_session_factory(
            access_role="freeBusyReader", external_event_id="existing_event_id"
        )
        client = self._client()

        result = await self._push(session_factory, client)

        assert result["status"] == "ignored"
        assert result["reason"] == "read_only_calendar"
        client.update_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_read_only_calendar_is_not_deleted_from(self) -> None:
        """Deleting is a write too, and this calendar refuses writes."""
        from worker import process_journal_event

        read_only = MagicMock()
        read_only.google_calendar_id = "shared@example.com"
        roles_result = MagicMock()
        roles_result.__iter__.return_value = iter([read_only])

        auth_row = MagicMock()
        auth_row.google_account_email = "test@example.com"
        auth_result = MagicMock()
        auth_result.fetchone.return_value = auth_row

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [auth_result, roles_result]
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

        client = AsyncMock()

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=client),
        ):
            result = await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 1,
                    "user_id": "test_user",
                    "external_identifiers": {
                        "google": [
                            {
                                "external_event_id": "existing_event_id",
                                "google_calendar_id": "shared@example.com",
                            }
                        ]
                    },
                },
            )

        assert result["status"] == "success"
        assert result["read_only_event_ids"] == ["existing_event_id"]
        assert result["external_event_ids"] == []
        client.delete_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_refused_update_is_not_retried(self, google_http_error) -> None:
        """Retrying a refusal earns the same 403 until it dead-letters."""
        session_factory = _push_session_factory(external_event_id="existing_event_id")
        client = self._client()
        client.update_event.side_effect = google_http_error(
            403, _forbidden_body("forbidden")
        )

        result = await self._push(session_factory, client)

        assert result["status"] == "ignored"
        assert result["reason"] == "forbidden"

    @pytest.mark.asyncio
    async def test_a_refused_update_marks_the_link_errored(
        self, google_http_error
    ) -> None:
        session_factory = _push_session_factory(external_event_id="existing_event_id")
        mock_session = session_factory.return_value.__aenter__.return_value
        client = self._client()
        client.update_event.side_effect = google_http_error(
            403, _forbidden_body("forbidden")
        )

        await self._push(session_factory, client)

        assert [
            call
            for call in mock_session.execute.call_args_list
            if "journal_external_event_links" in str(call[0][0])
            and len(call[0]) > 1
            and call[0][1].get("status") == "errored"
        ]

    @pytest.mark.asyncio
    async def test_a_refused_update_refreshes_the_access_role(
        self, google_http_error
    ) -> None:
        """The stored role is stale — that is why the push was attempted."""
        session_factory = _push_session_factory(external_event_id="existing_event_id")
        client = self._client()
        client.update_event.side_effect = google_http_error(
            403, _forbidden_body("forbidden")
        )

        await self._push(session_factory, client)

        client.list_calendars.assert_called()

    @pytest.mark.asyncio
    async def test_a_refused_create_is_not_retried(self, google_http_error) -> None:
        session_factory = _push_session_factory()
        client = self._client()
        client.create_event.side_effect = google_http_error(
            403, _forbidden_body("forbidden")
        )

        result = await self._push(session_factory, client, "JournalCreated")

        assert result["status"] == "ignored"
        assert result["reason"] == "forbidden"

    @pytest.mark.asyncio
    async def test_a_non_organizer_refusal_is_not_retried(
        self, google_http_error
    ) -> None:
        """Not every refusal is about the calendar; some are about the event."""
        session_factory = _push_session_factory(external_event_id="existing_event_id")
        client = self._client()
        client.update_event.side_effect = google_http_error(
            403, _forbidden_body("forbiddenForNonOrganizer")
        )

        result = await self._push(session_factory, client)

        assert result["reason"] == "forbidden"

    @pytest.mark.asyncio
    async def test_a_rate_limited_update_still_raises(self, google_http_error) -> None:
        """A 403 that means "too fast" has to keep its retries."""
        from googleapiclient.errors import HttpError

        session_factory = _push_session_factory(external_event_id="existing_event_id")
        client = self._client()
        client.update_event.side_effect = google_http_error(
            403, _forbidden_body("rateLimitExceeded")
        )

        with pytest.raises(HttpError):
            await self._push(session_factory, client)


class TestForbiddenDeletes:
    """Deleting an event Google will not let us delete."""

    @staticmethod
    def _session_factory() -> MagicMock:
        auth_result = MagicMock()
        auth_row = MagicMock()
        auth_row.google_account_email = "test@example.com"
        auth_result.fetchone.return_value = auth_row

        roles_result = MagicMock()
        roles_result.__iter__.return_value = iter([])

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [auth_result, roles_result]

        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
        return mock_factory

    @staticmethod
    async def _delete(session_factory: MagicMock, client: AsyncMock) -> dict[str, Any]:
        from worker import process_journal_event

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=client),
        ):
            return await process_journal_event(
                ctx={"session_factory": session_factory, "job_id": "job123"},
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 1,
                    "user_id": "test_user",
                    "external_identifiers": {"google": ["existing_event_id"]},
                },
            )

    @pytest.mark.asyncio
    async def test_a_refused_delete_does_not_fail_the_job(
        self, google_http_error
    ) -> None:
        """The copy stays on Google, and no retry can remove it."""
        client = AsyncMock()
        client.delete_event.side_effect = google_http_error(
            403, _forbidden_body("forbidden")
        )

        result = await self._delete(self._session_factory(), client)

        assert result["status"] == "success"
        assert result["external_event_ids"] == []
        assert result["forbidden_event_ids"] == ["existing_event_id"]

    @pytest.mark.asyncio
    async def test_a_rate_limited_delete_still_fails_the_job(
        self, google_http_error
    ) -> None:
        client = AsyncMock()
        client.delete_event.side_effect = google_http_error(
            403, _forbidden_body("rateLimitExceeded")
        )

        with pytest.raises(RuntimeError):
            await self._delete(self._session_factory(), client)


class TestReadOnlyCalendarPredicate:
    """One answer to "may we write to this calendar?", used by every writer."""

    @pytest.mark.parametrize("role", ["reader", "freeBusyReader", "none"])
    def test_roles_without_write_access_refuse_writes(self, role: str) -> None:
        """ "none" is Google's value for a calendar we can no longer reach."""
        from worker import is_read_only_calendar

        assert is_read_only_calendar(role) is True

    @pytest.mark.parametrize("role", ["owner", "writer"])
    def test_writable_roles_do_not(self, role: str) -> None:
        from worker import is_read_only_calendar

        assert is_read_only_calendar(role) is False

    def test_an_unknown_role_is_treated_as_writable(self) -> None:
        """A role we have never stored must not silently stop syncing."""
        from worker import is_read_only_calendar

        assert is_read_only_calendar(None) is False
