"""
Integration tests for releasing a deleted gear-usage journal's checkouts.

``JournalDeleted`` arrives after the journal and its gear items are gone, so
only the journal's ``snipeit_checkout`` rows are left. A successful checkout is
checked in; a failed or abandoned one may still have checked the asset out (a
lost response), so its asset is returned when nothing else may hold it, and its
rows are deleted either way — no later sync can reach a deleted journal's rows.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

# ``mock_transport`` and ``snipeit_sync_service`` (user-123, mapped to Snipe-IT
# user 5) are shared fixtures defined in ``conftest.py``.

DELETED_JOURNAL_ID = 913613
OTHER_JOURNAL_ID = 913614
_CHECKIN_41 = "/api/v1/hardware/41/checkin"
_MAPPED_USER = {"id": 5, "name": "Harry", "type": "user"}


async def _insert_checkout_row(
    async_connection: AsyncConnection,
    *,
    asset_id: int,
    journal_id: int = DELETED_JOURNAL_ID,
    sync_status: str,
    age_seconds: int = 0,
    user_id: str = "user-123",
    posted: bool = True,
) -> None:
    """Insert a ``snipeit_checkout`` row last touched ``age_seconds`` ago.

    ``posted`` (the default here) marks an attempt that got as far as posting
    the checkout, as a lost response leaves it.
    """
    await async_connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status, reference_data,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                (:user_id, 'snipeit_checkout', :external_id, :journal_id,
                 now(), 'hash', :sync_status, :reference_data, NULL, 0,
                 now() - make_interval(secs => :age_seconds),
                 now() - make_interval(secs => :age_seconds))
        """),
        {
            "user_id": user_id,
            "external_id": f"snipeit_checkout:{asset_id}:{journal_id}",
            "journal_id": str(journal_id),
            "sync_status": sync_status,
            "age_seconds": age_seconds,
            "reference_data": json.dumps({"posting": True}) if posted else None,
        },
    )


async def _checkout_rows(async_connection: AsyncConnection) -> set[tuple[str, str]]:
    """The (user, external id) of every checkout row left for the test journals."""
    result = await async_connection.execute(
        text("""
            SELECT user_id, external_id FROM sync_metadata
            WHERE integration_source = 'snipeit_checkout'
              AND internal_uuid IN (:deleted, :other)
        """),
        {"deleted": str(DELETED_JOURNAL_ID), "other": str(OTHER_JOURNAL_ID)},
    )
    return {(row.user_id, row.external_id) for row in result.fetchall()}


def _queue_asset(mock_transport: Any, assigned_to: dict[str, Any] | None) -> None:
    mock_transport.add_response(
        "/hardware/41",
        json_data={"id": 41, "asset_tag": "T-41", "assigned_to": assigned_to},
        method="GET",
    )


def _posts(mock_transport: Any) -> list[str]:
    return [r.url.path for r in mock_transport.requests if r.method == "POST"]


async def _release(
    snipeit_sync_service: Any, async_connection: AsyncConnection
) -> None:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    await snipeit_sync_service.release_deleted_journal(
        journal_id=DELETED_JOURNAL_ID, session_factory=session_factory
    )


class TestReleaseDeletedJournalIntegration:
    """Every checkout row of a deleted journal is released, whatever its status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("sync_status", "age_seconds"),
        [("failed", 0), ("pending", 3600)],
        ids=["failed", "abandoned-pending"],
    )
    async def test_an_abandoned_checkout_returns_its_asset_and_is_forgotten(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        sync_status: str,
        age_seconds: int,
    ) -> None:
        """A lost checkout response may have left the asset out to the user."""
        await _insert_checkout_row(
            async_connection,
            asset_id=41,
            sync_status=sync_status,
            age_seconds=age_seconds,
        )
        _queue_asset(mock_transport, _MAPPED_USER)
        mock_transport.add_response(
            "/hardware/41/checkin",
            json_data={"status": "success", "messages": "Checked in."},
            method="POST",
        )

        await _release(snipeit_sync_service, async_connection)

        checkin = next(r for r in mock_transport.requests if r.method == "POST")
        assert checkin.url.path == _CHECKIN_41
        assert json.loads(checkin.content)["note"] == "Gear usage journal deleted"
        assert await _checkout_rows(async_connection) == set()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "assigned_to",
        [None, {"id": 9, "name": "Someone else", "type": "user"}],
        ids=["not-out", "out-to-another-user"],
    )
    async def test_an_asset_not_out_to_the_user_is_left_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        assigned_to: dict[str, Any] | None,
    ) -> None:
        """The failed checkout never took the asset, so there is nothing to return."""
        await _insert_checkout_row(async_connection, asset_id=41, sync_status="failed")
        _queue_asset(mock_transport, assigned_to)

        await _release(snipeit_sync_service, async_connection)

        assert _posts(mock_transport) == []
        assert await _checkout_rows(async_connection) == set()

    @pytest.mark.asyncio
    async def test_an_attempt_that_never_posted_leaves_the_asset_alone(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """An attempt that failed before posting cannot have taken the asset.

        The asset may still be out to the user — by hand, or through a checkout
        the attempt linked — and that checkout is not this journal's to end.
        """
        await _insert_checkout_row(
            async_connection, asset_id=41, sync_status="failed", posted=False
        )

        await _release(snipeit_sync_service, async_connection)

        assert mock_transport.requests == []
        assert await _checkout_rows(async_connection) == set()

    @pytest.mark.asyncio
    async def test_an_asset_another_pair_may_hold_stays_out(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Returning an asset still in use is not recoverable; leaving it out is.

        The deleted journal's rows still go: nothing would ever retry them.
        """
        await _insert_checkout_row(async_connection, asset_id=41, sync_status="failed")
        await _insert_checkout_row(
            async_connection,
            asset_id=41,
            journal_id=OTHER_JOURNAL_ID,
            sync_status="failed",
        )
        _queue_asset(mock_transport, _MAPPED_USER)

        await _release(snipeit_sync_service, async_connection)

        assert _posts(mock_transport) == []
        assert await _checkout_rows(async_connection) == {
            ("user-123", f"snipeit_checkout:41:{OTHER_JOURNAL_ID}")
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("assigned_to", "checkin_status"),
        [(None, 404), (_MAPPED_USER, 403), (_MAPPED_USER, 404)],
        ids=["asset-gone", "checkin-forbidden", "checkin-not-found"],
    )
    async def test_a_terminal_snipeit_error_still_forgets_the_rows(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        assigned_to: dict[str, Any] | None,
        checkin_status: int,
    ) -> None:
        """A missing or forbidden asset cannot be returned by a retry either."""
        await _insert_checkout_row(async_connection, asset_id=41, sync_status="failed")
        if assigned_to is None:
            mock_transport.add_response(
                "/hardware/41", status_code=404, json_data=None, method="GET"
            )
        else:
            _queue_asset(mock_transport, assigned_to)
            mock_transport.add_response(
                "/hardware/41/checkin",
                status_code=checkin_status,
                json_data={"status": "error"},
                method="POST",
            )

        await _release(snipeit_sync_service, async_connection)

        assert await _checkout_rows(async_connection) == set()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failing", ["read", "checkin"])
    async def test_a_transient_snipeit_error_keeps_the_rows_for_a_retry(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
        failing: str,
    ) -> None:
        """The redelivered event must still find the row to return the asset from."""
        from snipeit_api_client import SnipeItAPIError

        await _insert_checkout_row(async_connection, asset_id=41, sync_status="failed")
        if failing == "read":
            mock_transport.add_response(
                "/hardware/41", status_code=500, json_data=None, method="GET"
            )
        else:
            _queue_asset(mock_transport, _MAPPED_USER)
            mock_transport.add_response(
                "/hardware/41/checkin",
                status_code=500,
                json_data={"status": "error"},
                method="POST",
            )

        with pytest.raises(SnipeItAPIError):
            await _release(snipeit_sync_service, async_connection)

        assert await _checkout_rows(async_connection) == {
            ("user-123", f"snipeit_checkout:41:{DELETED_JOURNAL_ID}")
        }

    @pytest.mark.asyncio
    async def test_a_checkout_in_flight_is_retried(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """The in-flight checkout may still succeed; the retry then checks it in."""
        from snipeit_sync_service import SnipeItSyncInProgress

        await _insert_checkout_row(async_connection, asset_id=41, sync_status="pending")

        with pytest.raises(SnipeItSyncInProgress):
            await _release(snipeit_sync_service, async_connection)

        assert mock_transport.requests == []
        assert await _checkout_rows(async_connection) == {
            ("user-123", f"snipeit_checkout:41:{DELETED_JOURNAL_ID}")
        }

    @pytest.mark.asyncio
    async def test_successful_and_failed_checkouts_are_both_released(
        self,
        snipeit_sync_service: Any,
        mock_transport: Any,
        async_connection: AsyncConnection,
    ) -> None:
        """Only this user's rows are touched, though journal ids are global."""
        await _insert_checkout_row(async_connection, asset_id=41, sync_status="failed")
        await _insert_checkout_row(async_connection, asset_id=42, sync_status="success")
        await _insert_checkout_row(
            async_connection, asset_id=43, sync_status="failed", user_id="user-456"
        )
        _queue_asset(mock_transport, _MAPPED_USER)
        for asset_id in (41, 42):
            mock_transport.add_response(
                f"/hardware/{asset_id}/checkin",
                json_data={"status": "success", "messages": "Checked in."},
                method="POST",
            )

        await _release(snipeit_sync_service, async_connection)

        assert _posts(mock_transport) == [_CHECKIN_41, "/api/v1/hardware/42/checkin"]
        assert await _checkout_rows(async_connection) == {
            ("user-123", f"snipeit_checkout:42:{DELETED_JOURNAL_ID}"),
            ("user-456", f"snipeit_checkout:43:{DELETED_JOURNAL_ID}"),
        }
