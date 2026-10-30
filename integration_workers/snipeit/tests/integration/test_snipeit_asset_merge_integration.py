"""Integration tests for the per-column merge of gear edits with Snipe-IT (#1898).

A gear edit is pushed column by column against the base the asset's link
records, so a remote change to anything else no longer drops it, and the pull
keeps an edit still to be pushed rather than overwriting it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from core_shared.sync_base import serialise_synced_entries
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from asset_merge import AssetValues, base_of
from snipeit_data_transformer import SnipeItDataTransformer
from snipeit_models import SnipeItAsset
from snipeit_sync_service import SnipeItSyncService

# ``mock_transport`` and ``snipeit_sync_service`` are shared fixtures defined in
# ``conftest.py``.

ASSET_ID = 42
USER_ID = "user-123"

type SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _asset(**changes: Any) -> dict[str, Any]:
    """A Snipe-IT GET body for the asset as last synced, with ``changes``."""
    return {
        "id": ASSET_ID,
        "name": "Tent",
        "asset_tag": "T-42",
        "serial": "SN-1",
        "model": {"id": 1, "name": "Hubba"},
        "manufacturer": {"id": 2, "name": "MSR"},
        "purchase_date": {"date": "2024-01-15", "formatted": "15/01/2024"},
        "status_label": {"id": 2, "name": "Ready to Deploy"},
        **changes,
    }


CHECKED_OUT: dict[str, Any] = {
    "status_label": {"id": 3, "name": "Deployed"},
    "assigned_to": {"id": 5, "name": "Someone", "type": "user"},
}


def _version(body: dict[str, Any]) -> str:
    return SnipeItDataTransformer.transform(
        SnipeItAsset.model_validate(body), user_id=USER_ID
    ).version_hash


def _values(body: dict[str, Any]) -> AssetValues:
    return AssetValues.of(
        SnipeItDataTransformer.transform(
            SnipeItAsset.model_validate(body), user_id=USER_ID
        ).gear_item
    )


def _serialised_base(body: dict[str, Any]) -> dict[str, list[str]]:
    return serialise_synced_entries(base_of(_values(body)))


@pytest.fixture
def session_factory(async_connection: AsyncConnection) -> SessionFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    return factory


async def _linked_gear(
    connection: AsyncConnection,
    *,
    name: str = "Tent",
    serial_number: str = "SN-1",
    version_hash: str | None = None,
    reference_data: dict[str, Any] | None = None,
) -> str:
    """A gear item linked to asset 42, recorded as synced from ``_asset()``."""
    row = (
        await connection.execute(
            text("""
                INSERT INTO gear_items
                    (user_id, name, serial_number, purchase_date, model, manufacturer)
                VALUES (:user_id, :name, :serial, '2024-01-15', 'Hubba', 'MSR')
                RETURNING id
            """),
            {"user_id": USER_ID, "name": name, "serial": serial_number},
        )
    ).one()
    gear_id = str(row.id)
    await connection.execute(
        text("""
            INSERT INTO sync_metadata
                (user_id, integration_source, external_id, internal_uuid,
                 last_synced_at, version_hash, sync_status, retry_count,
                 reference_data, created_at, updated_at)
            VALUES
                (:user_id, 'snipeit', :external_id, :gear_id,
                 now(), :version_hash, 'success', 0,
                 :reference_data, now(), now())
        """),
        {
            "user_id": USER_ID,
            "external_id": str(ASSET_ID),
            "gear_id": gear_id,
            "version_hash": version_hash or _version(_asset()),
            "reference_data": (
                None if reference_data is None else json.dumps(reference_data)
            ),
        },
    )
    return gear_id


def _synced_reference() -> dict[str, Any]:
    return {"synced_entries": _serialised_base(_asset())}


async def _link(connection: AsyncConnection) -> Any:
    return (
        await connection.execute(
            text("""
                SELECT version_hash, reference_data
                FROM sync_metadata
                WHERE integration_source = 'snipeit' AND external_id = :external_id
            """),
            {"external_id": str(ASSET_ID)},
        )
    ).one()


async def _gear(connection: AsyncConnection, gear_id: str) -> Any:
    return (
        await connection.execute(
            text("""
                SELECT name, serial_number, purchase_date
                FROM gear_items WHERE id = :id
            """),
            {"id": gear_id},
        )
    ).one()


def _queue_push(transport: Any, before: dict[str, Any], after: dict[str, Any]) -> None:
    """Snipe-IT's answers to a push: the asset, the PATCH, the asset again."""
    transport.add_response(f"/hardware/{ASSET_ID}", json_data=before, method="GET")
    transport.add_response(
        f"/hardware/{ASSET_ID}",
        json_data={"status": "success", "messages": "ok", "payload": after},
        method="PATCH",
    )
    transport.add_response(f"/hardware/{ASSET_ID}", json_data=after, method="GET")


def _patch_bodies(transport: Any) -> list[dict[str, Any]]:
    return [
        json.loads(request.content)
        for request in transport.requests
        if request.method == "PATCH"
    ]


@dataclass(frozen=True)
class PushCase:
    """A gear edit pushed against an asset Snipe-IT may have changed too.

    ``base`` is the asset whose values the link should record as its base.
    """

    local_name: str
    reference_data: dict[str, Any] | None
    before: dict[str, Any]
    after: dict[str, Any]
    base: dict[str, Any]
    pending_import: bool


PUSH_CASES = [
    pytest.param(
        PushCase(
            local_name="Big Tent",
            reference_data=_synced_reference(),
            before=_asset(**CHECKED_OUT),
            after=_asset(name="Big Tent", **CHECKED_OUT),
            base=_asset(name="Big Tent", **CHECKED_OUT),
            pending_import=False,
        ),
        id="pushed-although-the-asset-was-checked-out",
    ),
    pytest.param(
        PushCase(
            local_name="Big Tent",
            reference_data=_synced_reference(),
            before=_asset(serial="SN-2"),
            after=_asset(name="Big Tent", serial="SN-2"),
            # The serial keeps its base, so the pull reads it as Snipe-IT's change.
            base=_asset(name="Big Tent"),
            pending_import=True,
        ),
        id="a-remote-only-change-is-left-for-the-pull",
    ),
    pytest.param(
        PushCase(
            local_name="Big Tent",
            reference_data=_synced_reference(),
            before=_asset(name="Remote Tent"),
            after=_asset(name="Big Tent"),
            base=_asset(name="Big Tent"),
            pending_import=False,
        ),
        id="a-conflict-sends-the-local-value",
    ),
    pytest.param(
        PushCase(
            local_name="Big Tent",
            reference_data=None,
            before=_asset(serial="SN-2"),
            after=_asset(name="Big Tent", serial="SN-2"),
            base=_asset(name="Big Tent"),
            pending_import=True,
        ),
        id="a-link-without-a-base-merges-against-the-old-values",
    ),
]


class TestPushAssetUpdate:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", PUSH_CASES)
    async def test_only_the_local_edit_is_patched(
        self,
        case: PushCase,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        gear_id = await _linked_gear(
            async_connection,
            name=case.local_name,
            reference_data=case.reference_data,
        )
        _queue_push(mock_transport, case.before, case.after)

        await snipeit_sync_service.push_asset_update(
            gear_item_id=gear_id,
            changed_fields={"name": ["Tent", case.local_name]},
            session_factory=session_factory,
        )

        assert _patch_bodies(mock_transport) == [{"name": case.local_name}]
        link = await _link(async_connection)
        assert link.version_hash == _version(case.after)
        reference = json.loads(link.reference_data)
        assert reference["synced_entries"] == _serialised_base(case.base)
        assert reference["pending_import"] is case.pending_import

    @pytest.mark.asyncio
    async def test_nothing_local_to_push_sends_nothing(
        self,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        gear_id = await _linked_gear(
            async_connection, reference_data=_synced_reference()
        )
        mock_transport.add_response(
            f"/hardware/{ASSET_ID}", json_data=_asset(serial="SN-2"), method="GET"
        )

        await snipeit_sync_service.push_asset_update(
            gear_item_id=gear_id,
            changed_fields={"model": ["Hubba", "Hubba Hubba"]},
            session_factory=session_factory,
        )

        assert _patch_bodies(mock_transport) == []
        link = await _link(async_connection)
        assert link.version_hash == _version(_asset())
        assert json.loads(link.reference_data) == _synced_reference()


class TestPullKeepsTheBase:
    @pytest.mark.asyncio
    async def test_a_pull_records_the_base_on_a_link_without_one(
        self,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        gear_id = await _linked_gear(async_connection, version_hash="stale")
        remote = _asset(serial="SN-2")
        mock_transport.add_response(
            f"/hardware/{ASSET_ID}", json_data=remote, method="GET"
        )

        result = await snipeit_sync_service.sync_asset_batch(
            asset_ids=[ASSET_ID], session_factory=session_factory
        )

        assert result["synced"] == 1
        gear = await _gear(async_connection, gear_id)
        assert gear.serial_number == "SN-2"
        reference = json.loads((await _link(async_connection)).reference_data)
        assert reference["synced_entries"] == _serialised_base(remote)
        assert reference["pending_import"] is False

    @pytest.mark.asyncio
    async def test_a_pull_keeps_an_edit_still_to_push(
        self,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        gear_id = await _linked_gear(
            async_connection, name="Big Tent", reference_data=_synced_reference()
        )
        remote = _asset(serial="SN-2", **CHECKED_OUT)
        mock_transport.add_response(
            f"/hardware/{ASSET_ID}", json_data=remote, method="GET"
        )

        await snipeit_sync_service.sync_asset_batch(
            asset_ids=[ASSET_ID], session_factory=session_factory
        )

        gear = await _gear(async_connection, gear_id)
        assert (gear.name, gear.serial_number) == ("Big Tent", "SN-2")
        reference = json.loads((await _link(async_connection)).reference_data)
        assert reference["synced_entries"] == _serialised_base(remote)

    @pytest.mark.asyncio
    async def test_a_pending_import_is_applied_at_an_unchanged_version(
        self,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        remote = _asset(name="Big Tent", serial="SN-2")
        gear_id = await _linked_gear(
            async_connection,
            name="Big Tent",
            version_hash=_version(remote),
            reference_data={
                "synced_entries": _serialised_base(_asset(name="Big Tent")),
                "pending_import": True,
            },
        )
        mock_transport.add_response(
            f"/hardware/{ASSET_ID}", json_data=remote, method="GET"
        )

        result = await snipeit_sync_service.sync_asset_batch(
            asset_ids=[ASSET_ID], session_factory=session_factory
        )

        assert result["synced"] == 1
        gear = await _gear(async_connection, gear_id)
        assert (gear.name, gear.serial_number, gear.purchase_date) == (
            "Big Tent",
            "SN-2",
            date(2024, 1, 15),
        )
        reference = json.loads((await _link(async_connection)).reference_data)
        assert reference["pending_import"] is False


class TestPushRecordsTheBase:
    @pytest.mark.asyncio
    async def test_a_remote_change_after_a_push_is_pulled(
        self,
        snipeit_sync_service: SnipeItSyncService,
        mock_transport: Any,
        async_connection: AsyncConnection,
        session_factory: SessionFactory,
    ) -> None:
        gear_id = await _linked_gear(
            async_connection, name="Big Tent", reference_data=_synced_reference()
        )
        pushed = _asset(name="Big Tent")
        _queue_push(mock_transport, _asset(), pushed)

        await snipeit_sync_service.push_asset_update(
            gear_id, {"name": ["Tent", "Big Tent"]}, session_factory
        )

        reference = json.loads((await _link(async_connection)).reference_data)
        assert reference["synced_entries"] == _serialised_base(pushed)

        mock_transport.add_response(
            f"/hardware/{ASSET_ID}",
            json_data=_asset(name="Remote Tent"),
            method="GET",
        )
        await snipeit_sync_service.sync_asset_batch(
            asset_ids=[ASSET_ID], session_factory=session_factory
        )

        assert (await _gear(async_connection, gear_id)).name == "Remote Tent"
