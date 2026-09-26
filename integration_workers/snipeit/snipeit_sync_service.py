"""
Snipe-IT Sync Service — orchestrates gear item and maintenance import.

Fetches assets and maintenance records from the Snipe-IT API, transforms
them using ``SnipeItDataTransformer`` / ``SnipeItMaintenanceTransformer``,
and upserts them into the database. Sync state is tracked via ``SyncMetadata``.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import structlog
from core_shared.models.journals.calendar_info import event_date_in_timezone
from sqlalchemy import text

from snipeit_api_client import SnipeItAPIClient, SnipeItAPIError
from snipeit_data_transformer import SnipeItDataTransformer
from snipeit_maintenance_transformer import SnipeItMaintenanceTransformer
from snipeit_models import SnipeItActivity, SnipeItAsset, SnipeItMaintenance
from snipeit_rate_limiter import SnipeItRateLimitError

logger = structlog.get_logger(__name__)

# Maximum assets per Snipe-IT API page
_PAGE_SIZE = 50

# Most activity-report pages searched for an existing checkout or check-in
_ACTIVITY_MAX_PAGES = 10

# Most maintenance-list pages searched for a record an earlier push created
_MAINTENANCE_MAX_PAGES = 10


def _resolve_zone(*candidates: object) -> str | None:
    """Return the first candidate naming a zone ``ZoneInfo`` can load, else ``None``.

    Settings are user input and a row column may be absent, so anything that is
    not a loadable zone name is skipped rather than trusted.
    """
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        return candidate
    return None


def _local_date(value: date | datetime | str | None, zone: str | None) -> date | None:
    """Return the calendar date ``value`` falls on in ``zone``.

    Journal date ranges are stored as the UTC instant of a *local* midnight, so
    taking the date of the stored UTC value lands a day early east of UTC.
    Plain dates are already calendar dates; strings are read by their ISO date
    prefix. Returns ``None`` for missing or unparseable input.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return event_date_in_timezone(value, zone)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _format_date_for_snipeit(
    value: date | datetime | str | None, zone: str | None
) -> str | None:
    """Format ``value`` as the ``YYYY-MM-DD`` local date the Snipe-IT API takes."""
    local = _local_date(value, zone)
    return local.isoformat() if local else None


# Snipe-IT's naive ``Y-m-d H:i:s`` datetime format.
_SNIPEIT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ``reference_data`` key of the asset dates read before a checkout.
_ASSET_DATES_BEFORE = "asset_dates_before"

# ``reference_data`` key marking a checkout whose POST may have reached Snipe-IT
# before its log entry was claimed.
_POSTING = "posting"


def _snipeit_zone(row: Any) -> str | None:
    """Return the zone every date and time sent to Snipe-IT is read in.

    Snipe-IT stores dates and times naive in its server's zone, which its API
    does not expose. The user's configured zone stands in for it (``None``, i.e.
    UTC, when unset). One zone is used for every value, even for an event in
    another zone: a checkout's time and the date its log is looked up by must
    land on the same day.
    """
    return _resolve_zone(getattr(row, "user_timezone", None))


def _snipeit_wall_clock(
    value: date | datetime | None, zone: str | None
) -> datetime | None:
    """Return ``value`` as a naive wall-clock datetime in ``zone``.

    Naive datetimes are UTC (the storage convention); a plain date is its
    midnight. ``zone`` must be loadable (see :func:`_snipeit_zone`).
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        return datetime.combine(value, time())
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo(zone) if zone else UTC).replace(tzinfo=None)


def _format_wall_clock(value: datetime | None) -> str | None:
    """Format a naive wall-clock datetime the way Snipe-IT stores it."""
    return value.strftime(_SNIPEIT_DATETIME_FORMAT) if value else None


def _parse_wall_clock(value: object) -> datetime | None:
    """Parse a Snipe-IT ``Y-m-d H:i:s`` string, or ``None`` when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        # Naive on purpose: Snipe-IT's wall-clock times carry no zone.
        return datetime.strptime(value, _SNIPEIT_DATETIME_FORMAT)  # noqa: DTZ007
    except ValueError:
        return None


def _snipeit_datetime(value: date | datetime | None, zone: str | None) -> str | None:
    """Format ``value`` as the naive ``Y-m-d H:i:s`` wall-clock time in ``zone``."""
    return _format_wall_clock(_snipeit_wall_clock(value, zone))


def _activity_matches_time(
    activity: SnipeItActivity, at: str | None, *, exact: bool = False
) -> bool:
    """Whether ``activity`` may be the log entry of an action at wall-clock ``at``.

    A checkout the worker posts carries its time of day, so an entry at another
    time is another usage of the asset that day. An entry at midnight was
    entered as a date (by hand, or posted before times were sent) and matches
    any time of that day, unless ``exact`` asks for the entry of one checkout.
    An entry with no action time (dated today) and a lookup with no ``at``
    (check-ins keep no time of day) are not constrained.
    """
    wall_clock = activity.action_wall_clock
    if at is None or wall_clock is None:
        return True
    if wall_clock == at:
        return True
    return not exact and wall_clock.endswith(" 00:00:00")


async def _fetch_journal_row(session: Any, journal_id: int) -> Any:
    """Fetch a journal's title, content and dates, with the zone they are sent in."""
    result = await session.execute(
        text("""
            SELECT j.title, j.content,
                   j.event_date_range_start, j.event_date_range_end,
                   us.timezone AS user_timezone
            FROM journals j
            LEFT JOIN user_settings us ON us.user_id = j.user_id
            WHERE j.id = :journal_id
        """),
        {"journal_id": journal_id},
    )
    return result.fetchone()


# UTC-12, the last zone to reach each date: no server's date is behind it.
_EARLIEST_ZONE = ZoneInfo("Etc/GMT+12")


def _snipeit_checkin_at(
    local_checkin: date | None, *, now: datetime | None = None
) -> date | None:
    """Return the historical ``checkin_at`` to send Snipe-IT, or ``None`` for "now".

    Snipe-IT compares ``checkin_at`` with its own server date, whose zone we do
    not know, and must never be sent a date it reads as the future. A date is
    only sent once it has passed at UTC-12, by which point it has passed on
    every server; a more recent return is stamped at the server's time instead.
    """
    if local_checkin is None:
        return None
    earliest_today = (now or datetime.now(tz=UTC)).astimezone(_EARLIEST_ZONE).date()
    return local_checkin if local_checkin < earliest_today else None


def _checkout_asset_id(external_id: object) -> int | None:
    """Return the asset id in a ``snipeit_checkout:{asset}:{journal}`` external id."""
    try:
        return int(str(external_id).split(":")[1])
    except (ValueError, IndexError):
        return None


def _usage_period_has_ended(
    value: date | datetime | str | None, *, now: datetime | None = None
) -> bool:
    """Return ``True`` if the usage period end ``value`` is in the past.

    Compares full timestamps against ``now`` (consistent with the periodic
    sweep's ``COALESCE(...) < now()`` query), so a check-in time earlier *today*
    is correctly treated as past — a date-only comparison would leave the asset
    checked out until the next calendar day. Naive datetimes are assumed UTC.
    Returns ``False`` for falsy/unparseable inputs.
    """
    if value is None:
        return False
    now = now or datetime.now(tz=UTC)
    # ``datetime`` must be checked before ``date`` (datetime subclasses date).
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < now
    if isinstance(value, date):
        return value < now.date()
    # String fallback: only a valid ISO date prefix is comparable; anything
    # else is treated as not-past rather than risking a lexicographic mishit.
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return parsed < now.date()


# Internal signalling exceptions
class _AssetSkipped(Exception):
    """Raised when an asset was already imported (dedup)."""


class _AssetFailed(Exception):
    """Raised when an asset failed after all retries."""


class _MaintenanceSkipped(Exception):
    """Raised when a maintenance record was already imported (dedup)."""


class _MaintenanceFailed(Exception):
    """Raised when a maintenance record failed after all retries."""


# How long a pending checkout or check-in lock counts as held by a live worker.
# An older lock is assumed abandoned (its worker died) and is retaken, so the
# stream consumer's retry budget must outlast it (see stream_consumer_tasks).
IN_FLIGHT_LOCK_SECONDS = 300


class SnipeItSyncInProgress(Exception):
    """Raised when another worker holds a journal's Snipe-IT checkout.

    That worker may be recording older dates than the event that met it, so the
    event must be retried rather than dropped; the stream consumer redelivers it.
    """


_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    ConnectionError,
    OSError,
)


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, SnipeItAPIError) and exc.status_code >= 500:
        return True
    return False


_MAX_ASSET_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0

# Synthetic calendar UUID for Snipe-IT maintenance events.
# Generated deterministically: uuid5(NAMESPACE_URL, "snipeit:maintenance")
_SNIPEIT_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"

# The integration source of inbound maintenance syncs. The backend records it as
# ``changed_by`` on every journal update it applies from one, which is how the
# consumer tells a Snipe-IT-applied update from a user's edit.
INBOUND_SYNC_CHANGED_BY = "snipeit_maintenance"

# How long an import's sync row has to be answered with a journal link before
# the record is imported again instead.
#
# A row with no link means one of two things, and nothing in the schema tells
# them apart: the backend has not turned the event this row last wrote into a
# link yet, or the journal that link belonged to has been deleted. The row's
# ``last_synced_at`` is when that event was enqueued — an import writes it and
# nothing else does, since a push of an imported journal deliberately leaves
# the row alone — so its age is how long that event has gone unanswered.
#
# This only decides whether to wait or to import; nothing depends on it for
# correctness. No length of grace could: a create delivered and not
# acknowledged before the backend's consumer died can arrive after any amount
# of time, once that consumer is back. What keeps it from overwriting the
# journal the import creates is the backend, which applies a maintenance event
# only while this row still records that event's hash (see
# ``JournalOutboxEventProcessor._is_superseded_snipeit_maintenance``). The
# grace just keeps a sync from re-sending a create the backend is about to
# answer anyway.
IMPORT_LINK_GRACE_SECONDS = 900


def _snipeit_maintenance_id(external_id: str) -> int | None:
    """Return the Snipe-IT maintenance id in a ``snipeit_maint:{id}`` external id."""
    prefix, _, maintenance_id = external_id.partition(":")
    if prefix != "snipeit_maint" or not maintenance_id.isdigit():
        return None
    return int(maintenance_id)


# Integration source of the claim a maintenance push writes before posting. A
# claim row is keyed by journal id (``internal_uuid`` and ``external_id``).
_MAINTENANCE_CLAIM_SOURCE = "snipeit_maintenance_claim"


@dataclass(frozen=True)
class MaintenanceClaim:
    """The Snipe-IT maintenance record a journal's push is creating.

    Written on the journal's claim row before the record is posted and removed
    once the record's own sync row is written, so an attempt that fails after
    the POST still says what its record looks like.

    Attributes:
        asset_id: The Snipe-IT asset the record is on.
        title: The title sent, unescaped.
        start_date: The ``YYYY-MM-DD`` start date sent, if any.
    """

    asset_id: int
    title: str
    start_date: str | None

    @classmethod
    def for_payload(cls, asset_id: int, payload: dict[str, Any]) -> MaintenanceClaim:
        """The claim for posting ``payload`` on asset ``asset_id``."""
        return cls(
            asset_id=asset_id,
            title=str(payload["name"]),
            start_date=payload.get("start_date"),
        )

    def matches(self, maintenance: SnipeItMaintenance) -> bool:
        """Whether ``maintenance``, as Snipe-IT returns it, is the claimed record.

        Snipe-IT HTML-escapes titles on output but stores what it is sent.
        """
        return (
            maintenance.asset_id == self.asset_id
            and maintenance.title is not None
            and html.unescape(maintenance.title) == self.title
            and maintenance.start_date_str == self.start_date
        )

    def to_reference(self) -> str:
        """The claim as a claim row's ``reference_data``."""
        return json.dumps(
            {
                "asset_id": self.asset_id,
                "title": self.title,
                "start_date": self.start_date,
            }
        )

    @classmethod
    def from_reference(cls, reference_data: object) -> MaintenanceClaim | None:
        """Read a claim row's ``reference_data``, or ``None`` when it holds no claim."""
        if not isinstance(reference_data, str):
            return None
        try:
            data = json.loads(reference_data)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        asset_id = data.get("asset_id")
        title = data.get("title")
        start_date = data.get("start_date")
        if (
            not isinstance(asset_id, int)
            or not isinstance(title, str)
            or not (start_date is None or isinstance(start_date, str))
        ):
            return None
        return cls(asset_id=asset_id, title=title, start_date=start_date)


def _payload_version_hash(payload: dict[str, Any]) -> str:
    """The ``version_hash`` a push row records for the maintenance values ``payload``."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _snipeit_record_payload(maintenance: SnipeItMaintenance) -> dict[str, Any]:
    """A Snipe-IT maintenance's own values, in the shape a push sends them.

    Hashed for a linked record's push row, so the row says what the record
    holds rather than what the journal holds.
    """
    payload: dict[str, Any] = {
        "name": html.unescape(maintenance.title or ""),
        "notes": html.unescape(maintenance.notes or ""),
        "asset_maintenance_type": maintenance.asset_maintenance_type,
    }
    if maintenance.start_date_str:
        payload["start_date"] = maintenance.start_date_str
    if maintenance.completion_date_str:
        payload["completion_date"] = maintenance.completion_date_str
    return payload


async def _lock_asset_maintenances(session: Any, asset_id: int) -> None:
    """Serialise writes of maintenance claims and sync rows on one Snipe-IT asset."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"snipeit_maintenance:{asset_id}"},
    )


async def _delete_maintenance_claim(session: Any, journal_id: int) -> None:
    """Delete the journal's maintenance claim, if it has one."""
    await session.execute(
        text("""
            DELETE FROM sync_metadata
            WHERE integration_source = :claim_source
              AND external_id = :journal_id
        """),
        {"claim_source": _MAINTENANCE_CLAIM_SOURCE, "journal_id": str(journal_id)},
    )


async def _fetch_maintenance_claim(session: Any, journal_id: int) -> Any:
    """The journal's maintenance claim row, with its age in seconds, or ``None``."""
    result = await session.execute(
        text("""
            SELECT sync_status, reference_data,
                   extract(epoch from (now() - updated_at)) AS age_seconds
            FROM sync_metadata
            WHERE integration_source = :claim_source
              AND external_id = :journal_id
            FOR UPDATE
        """),
        {"claim_source": _MAINTENANCE_CLAIM_SOURCE, "journal_id": str(journal_id)},
    )
    return result.fetchone()


async def _journal_exists(session: Any, journal_id: int, *, lock: bool = False) -> bool:
    """Whether the journal is still there.

    A journal's rows outlive it: deleting one cascades its own tables, not the
    ``sync_metadata`` rows that name it by id.

    Args:
        session: The session to read in.
        journal_id: The journal to look for.
        lock: Hold the row with ``FOR SHARE`` until this transaction commits, so
            a deletion racing it cannot commit in between and leave a row naming
            a journal that has gone. Callers about to *write* such a row pass
            this; a read-only decision does not need it. The deletion then waits
            for this transaction, and its handler sees the row and cleans it up.
    """
    result = await session.execute(
        text(
            "SELECT 1 FROM journals WHERE id = :journal_id"
            + (" FOR SHARE" if lock else "")
        ),
        {"journal_id": journal_id},
    )
    return result.fetchone() is not None


async def _journal_holding_maintenance(session: Any, external_id: str) -> int | None:
    """The live journal linked to this Snipe-IT maintenance, if there is one.

    A link is written only for an imported record, and only by the backend once
    it has created the journal — so this answers "does the app still show this
    record?" without trusting the sync row, which outlives the journal it was
    written for.
    """
    result = await session.execute(
        text("""
            SELECT l.journal_id
            FROM journal_external_event_links l
            JOIN journals j ON j.id = l.journal_id
            WHERE l.external_event_id = :external_event_id
              AND l.calendar_id = :calendar_id
            LIMIT 1
        """),
        {
            "external_event_id": external_id,
            "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
        },
    )
    journal_id: int | None = result.scalar_one_or_none()
    return journal_id


async def _recorded_maintenance(session: Any, journal_id: int) -> str | None:
    """The ``snipeit_maint:{id}`` recorded as the journal's Snipe-IT maintenance."""
    result = await session.execute(
        text("""
            SELECT external_id
            FROM sync_metadata
            WHERE integration_source = 'snipeit_maintenance'
              AND internal_uuid = :journal_id
            LIMIT 1
        """),
        {"journal_id": str(journal_id)},
    )
    external_id: str | None = result.scalar_one_or_none()
    return external_id


def _unanswered_create_has_expired(meta_row: Any) -> bool:
    """Has this row waited too long for the journal link its create promised?

    ``True`` means the create has gone unanswered long enough to count as never
    coming — the journal it made was deleted, or the event was lost — so the
    record belongs to nothing and is imported again. A row whose age cannot be
    read is treated as still waiting, which costs no more than a later sync.
    """
    age_seconds = getattr(meta_row, "age_seconds", None)
    if age_seconds is None:
        return False
    return float(age_seconds) >= IMPORT_LINK_GRACE_SECONDS


def _raise_if_claim_in_flight(journal_id: int, claim_row: Any) -> None:
    """Raise when ``claim_row`` is pending and touched within the in-flight window.

    A failed claim, or one left by a worker that died, is not in flight.
    """
    if (
        claim_row is not None
        and claim_row.sync_status == "pending"
        and claim_row.age_seconds is not None
        and claim_row.age_seconds < IN_FLIGHT_LOCK_SECONDS
    ):
        raise SnipeItSyncInProgress(
            f"Maintenance create of journal {journal_id} is in flight"
        )


async def _insert_push_row(
    session: Any, journal_id: int, external_id: str, version_hash: str
) -> Literal["inserted", "taken", "journal_gone"]:
    """Record ``external_id`` as the journal's Snipe-IT maintenance.

    This is the only place a push row is written, so it is where a row can be
    stopped from naming a journal that is not there. A journal deleted while a
    push or an inbound claim-link was running would otherwise be recorded after
    the deletion handler had already looked for its rows, leaving a record no
    journal holds and the inbound sync skipped.

    Returns:
        ``"inserted"`` when the row was written, ``"taken"`` when a sync row
        already names that record — a record's row is never re-pointed to
        another journal — and ``"journal_gone"`` when the journal no longer
        exists. Nothing is written in the latter two cases.
    """
    if not await _journal_exists(session, journal_id, lock=True):
        return "journal_gone"

    result = await session.execute(
        text("""
            INSERT INTO sync_metadata
                (internal_uuid, integration_source, external_id,
                 last_synced_at, version_hash, sync_status,
                 error_message, retry_count, created_at, updated_at)
            VALUES
                (:internal_uuid, 'snipeit_maintenance', :external_id,
                 now(), :version_hash, 'success', NULL, 0, now(), now())
            ON CONFLICT (integration_source, external_id) DO NOTHING
            RETURNING id
        """),
        {
            "internal_uuid": str(journal_id),
            "external_id": external_id,
            "version_hash": version_hash,
        },
    )
    return "inserted" if result.fetchone() is not None else "taken"


@dataclass(frozen=True)
class MaintenancePushContext:
    """What pushing a GEAR_MAINTENANCE journal to Snipe-IT reads.

    Attributes:
        journal: The journal's title, content and dates, with the zones they are
            read in.
        maintenance: Its ``journal_gear_maintenance_data`` row.
        asset_meta: The sync row of the Snipe-IT asset its gear item is.
        imported_external_id: The ``snipeit_maint:{id}`` of the record a journal
            was imported from, or ``None`` for a journal a user wrote. The
            backend links every import to the synthetic maintenance calendar in
            the transaction that publishes its ``JournalCreated``, so the link is
            visible to any push that event triggers.
    """

    journal: Any
    maintenance: Any
    asset_meta: Any
    imported_external_id: str | None

    def snipeit_payload(self) -> dict[str, Any]:
        """The Snipe-IT maintenance fields the journal holds, dates read locally."""
        zone = _snipeit_zone(self.journal)
        return SnipeItMaintenanceTransformer.reverse_transform(
            title=self.journal.title or "",
            content=self.journal.content or "",
            maintenance_type=self.maintenance.maintenance_type or "routine maintenance",
            start_date=_format_date_for_snipeit(
                self.journal.event_date_range_start, zone
            ),
            end_date=_format_date_for_snipeit(self.journal.event_date_range_end, zone),
        )


class SnipeItSyncService:
    """Orchestrates Snipe-IT asset import into gear_items.

    Args:
        api_client: Authenticated ``SnipeItAPIClient``.
        user_id: Internal user ID that owns the Snipe-IT connection.
        snipeit_user_id: Optional Snipe-IT user ID to filter by assigned assets.
    """

    def __init__(
        self,
        api_client: SnipeItAPIClient,
        user_id: str,
        snipeit_user_id: str | None = None,
    ) -> None:
        self._api_client = api_client
        self._user_id = user_id
        self._snipeit_user_id = snipeit_user_id
        self._transformer = SnipeItDataTransformer()

    async def list_asset_batches(self) -> AsyncIterator[list[int]]:
        """Yield pages of Snipe-IT asset IDs for batch processing.

        Yields:
            Lists of Snipe-IT asset IDs, one list per API page.
        """
        page = 1
        while True:
            response = await self._api_client.list_assets(
                assigned_to_user_id=self._snipeit_user_id,
                page=page,
                per_page=_PAGE_SIZE,
            )

            if not response.rows:
                break

            asset_ids = [asset.id for asset in response.rows]
            logger.info(
                "Listed Snipe-IT asset batch",
                page=page,
                batch_size=len(asset_ids),
                total_expected=response.total,
            )
            yield asset_ids

            if page * _PAGE_SIZE >= response.total:
                break

            page += 1

        logger.info(
            "Finished listing asset batches",
            pages_fetched=page,
        )

    async def sync_asset_batch(
        self,
        asset_ids: list[int],
        session_factory: Any,
    ) -> dict[str, int]:
        """Process a batch of asset IDs, upserting gear_items.

        Args:
            asset_ids: Snipe-IT asset IDs to sync.
            session_factory: Async session factory for transactions.

        Returns:
            Dict with ``synced``, ``skipped``, and ``failed`` counts.
        """
        synced = 0
        skipped = 0
        failed = 0

        for asset_id in asset_ids:
            try:
                await self._sync_single_asset_with_retry(asset_id, session_factory)
                synced += 1
            except _AssetSkipped:
                skipped += 1
            except _AssetFailed:
                failed += 1

        logger.info(
            "Asset batch completed",
            batch_size=len(asset_ids),
            synced=synced,
            skipped=skipped,
            failed=failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    async def _sync_single_asset_with_retry(
        self,
        asset_id: int,
        session_factory: Any,
    ) -> None:
        last_exc: Exception | None = None
        external_id = str(asset_id)

        for attempt in range(1, _MAX_ASSET_RETRIES + 1):
            try:
                # Get the asset from API outside transaction
                asset = await self._api_client.get_asset(asset_id)
                transformed = self._transformer.transform(
                    asset=asset, user_id=self._user_id
                )

                async with session_factory() as session:
                    async with session.begin():
                        # Check existing metadata
                        result = await session.execute(
                            text("""
                                SELECT version_hash, internal_uuid
                                FROM sync_metadata
                                WHERE integration_source = 'snipeit'
                                  AND external_id = :external_id
                                FOR UPDATE
                            """),
                            {"external_id": external_id},
                        )
                        existing_meta = result.fetchone()

                        if (
                            existing_meta
                            and existing_meta.version_hash == transformed.version_hash
                        ):
                            logger.debug(
                                "Skipping unchanged Snipe-IT asset",
                                asset_id=asset_id,
                            )
                            raise _AssetSkipped

                        # Upsert gear item
                        gear_id = (
                            existing_meta.internal_uuid
                            if existing_meta and existing_meta.internal_uuid
                            else transformed.gear_item.id
                        )

                        await session.execute(
                            text("""
                                INSERT INTO gear_items (
                                    id, user_id, name, model, serial_number,
                                    purchase_date, manufacturer, updated_at
                                ) VALUES (
                                    :id, :user_id, :name, :model, :serial_number,
                                    :purchase_date, :manufacturer, now()
                                )
                                ON CONFLICT (id) DO UPDATE SET
                                    name = EXCLUDED.name,
                                    model = EXCLUDED.model,
                                    serial_number = EXCLUDED.serial_number,
                                    purchase_date = EXCLUDED.purchase_date,
                                    manufacturer = EXCLUDED.manufacturer,
                                    updated_at = now()
                                WHERE gear_items.user_id = EXCLUDED.user_id
                            """),
                            {
                                "id": gear_id,
                                "user_id": self._user_id,
                                "name": transformed.gear_item.name,
                                "model": transformed.gear_item.model,
                                "serial_number": transformed.gear_item.serial_number,
                                "purchase_date": transformed.gear_item.purchase_date,
                                "manufacturer": transformed.gear_item.manufacturer,
                            },
                        )

                        await session.execute(
                            text("""
                                INSERT INTO sync_metadata
                                    (internal_uuid, integration_source, external_id, last_synced_at,
                                     version_hash, sync_status, error_message, retry_count,
                                     created_at, updated_at)
                                VALUES
                                    (:internal_uuid, 'snipeit', :external_id, now(),
                                     :version_hash, 'success', NULL, 0,
                                     now(), now())
                                ON CONFLICT (integration_source, external_id)
                                DO UPDATE SET
                                    internal_uuid = EXCLUDED.internal_uuid,
                                    last_synced_at = EXCLUDED.last_synced_at,
                                    version_hash = EXCLUDED.version_hash,
                                    sync_status = EXCLUDED.sync_status,
                                    error_message = EXCLUDED.error_message,
                                    retry_count = 0,
                                    updated_at = EXCLUDED.updated_at
                            """),
                            {
                                "external_id": external_id,
                                "version_hash": transformed.version_hash,
                                "internal_uuid": gear_id,
                            },
                        )
                return

            except _AssetSkipped:
                raise
            except (SnipeItRateLimitError, Exception) as exc:
                if not _is_transient_error(exc) and not isinstance(
                    exc, SnipeItRateLimitError
                ):
                    logger.warning(
                        "Non-transient error syncing Snipe-IT asset",
                        asset_id=asset_id,
                        attempt=attempt,
                        exc_info=True,
                    )

                    # Log failure in metadata if possible
                    try:
                        async with session_factory() as session:
                            async with session.begin():
                                await session.execute(
                                    text("""
                                        INSERT INTO sync_metadata
                                            (integration_source, external_id, last_synced_at,
                                             version_hash, sync_status, error_message, retry_count,
                                             created_at, updated_at)
                                        VALUES
                                            ('snipeit', :external_id, now(),
                                             '', 'failed', :error_message, 0,
                                             now(), now())
                                        ON CONFLICT (integration_source, external_id)
                                        DO UPDATE SET
                                            last_synced_at = EXCLUDED.last_synced_at,
                                            sync_status = EXCLUDED.sync_status,
                                            error_message = EXCLUDED.error_message,
                                            retry_count = sync_metadata.retry_count + 1,
                                            updated_at = EXCLUDED.updated_at
                                    """),
                                    {
                                        "external_id": external_id,
                                        "error_message": str(exc),
                                    },
                                )
                    except Exception:  # noqa: BLE001
                        pass

                    raise _AssetFailed from exc

                last_exc = exc
                if isinstance(exc, SnipeItRateLimitError):
                    raise  # Bubble up to ARQ

                if attempt < _MAX_ASSET_RETRIES:
                    backoff = _RETRY_BACKOFF_BASE**attempt
                    await asyncio.sleep(backoff)

        logger.error(
            "Failed to sync asset after retries",
            asset_id=asset_id,
            error=str(last_exc),
        )
        raise _AssetFailed from last_exc

    async def push_asset_update(
        self,
        gear_item_id: str,
        changed_fields: dict[str, Any],
        session_factory: Any,
    ) -> None:
        """Push local gear item changes to Snipe-IT.

        Args:
            gear_item_id: Internal gear item UUID.
            changed_fields: Dictionary of field name to (old, new) array/tuple.
            session_factory: Async session factory for DB queries.
        """
        async with session_factory() as session:
            # 1. Get sync metadata for this gear item
            result = await session.execute(
                text("""
                    SELECT external_id, version_hash
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :internal_uuid
                    FOR UPDATE
                """),
                {"internal_uuid": gear_item_id},
            )
            meta = result.fetchone()

            if not meta:
                logger.debug(
                    "Skipping Snipe-IT export, no sync metadata found",
                    gear_item_id=gear_item_id,
                )
                return

            external_id = meta.external_id
            local_version_hash = meta.version_hash

        # 2. Fetch the current asset from Snipe-IT to verify hash
        try:
            asset = await self._api_client.get_asset(int(external_id))
        except SnipeItAPIError as exc:
            if exc.status_code == 404:
                logger.warning(
                    "Snipe-IT asset not found during export",
                    gear_item_id=gear_item_id,
                    external_id=external_id,
                )
                return
            raise

        transformed = self._transformer.transform(asset=asset, user_id=self._user_id)

        # 3. Check for conflict
        if transformed.version_hash != local_version_hash:
            logger.info(
                "Snipe-IT export conflict: remote asset changed since last sync. Skipping update.",
                gear_item_id=gear_item_id,
                external_id=external_id,
            )
            return

        # 4. Map changed fields to Snipe-IT API payload
        payload = {}
        if "name" in changed_fields:
            payload["name"] = changed_fields["name"][1]
        if "serial_number" in changed_fields:
            payload["serial"] = changed_fields["serial_number"][1]
        if "purchase_date" in changed_fields:
            new_date = changed_fields["purchase_date"][1]
            payload["purchase_date"] = new_date if new_date is not None else ""

        if not payload:
            logger.debug(
                "No mapped fields changed for Snipe-IT export",
                gear_item_id=gear_item_id,
            )
            return

        # 5. Push the update
        updated_asset = await self._api_client.update_asset(int(external_id), payload)

        # 6. Update sync metadata with the new version hash
        updated_transformed = self._transformer.transform(
            asset=updated_asset, user_id=self._user_id
        )

        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = :version_hash,
                            last_synced_at = now(),
                            updated_at = now()
                        WHERE integration_source = 'snipeit'
                          AND external_id = :external_id
                    """),
                    {
                        "version_hash": updated_transformed.version_hash,
                        "external_id": external_id,
                    },
                )

        logger.info(
            "Successfully pushed gear item update to Snipe-IT",
            gear_item_id=gear_item_id,
            external_id=external_id,
        )

    # -- Maintenance Sync Methods ------------------------------------------

    async def list_maintenance_batches(self) -> AsyncIterator[list[int]]:
        """Yield pages of Snipe-IT maintenance IDs for batch processing.

        Yields:
            Lists of Snipe-IT maintenance IDs, one list per API page.
        """
        page = 1
        while True:
            response = await self._api_client.list_maintenances(
                page=page,
                per_page=_PAGE_SIZE,
            )

            if not response.rows:
                break

            maintenance_ids = [m.id for m in response.rows]
            logger.info(
                "Listed Snipe-IT maintenance batch",
                page=page,
                batch_size=len(maintenance_ids),
                total_expected=response.total,
            )
            yield maintenance_ids

            if page * _PAGE_SIZE >= response.total:
                break

            page += 1

        logger.info(
            "Finished listing maintenance batches",
            pages_fetched=page,
        )

    async def sync_maintenance_batch(
        self,
        maintenance_ids: list[int],
        session_factory: Any,
    ) -> dict[str, int]:
        """Process a batch of maintenance IDs, creating outbox events.

        Args:
            maintenance_ids: Snipe-IT maintenance IDs to sync.
            session_factory: Async session factory for transactions.

        Returns:
            Dict with ``synced``, ``skipped``, and ``failed`` counts.
        """
        synced = 0
        skipped = 0
        failed = 0

        for maintenance_id in maintenance_ids:
            try:
                await self._sync_single_maintenance(maintenance_id, session_factory)
                synced += 1
            except _MaintenanceSkipped:
                skipped += 1
            except _MaintenanceFailed:
                failed += 1
            except SnipeItRateLimitError:
                # Not a failed record: the batch job defers the whole batch.
                raise
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Unexpected error syncing maintenance record",
                    maintenance_id=maintenance_id,
                    exc_info=True,
                )
                failed += 1

        logger.info(
            "Maintenance batch completed",
            batch_size=len(maintenance_ids),
            synced=synced,
            skipped=skipped,
            failed=failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    async def reconcile_deleted_maintenances(
        self, listed_ids: Collection[int], session_factory: Any
    ) -> int:
        """Forget the maintenance records Snipe-IT no longer has.

        A record deleted in Snipe-IT is simply missing from the next listing,
        so its sync row would stay behind for ever. The rows the full listing
        ``listed_ids`` did not return are the candidates. Each is looked up
        before it is forgotten, because a listing paged by offset can skip a
        record created or deleted while it ran.

        A gone record's row is deleted, except a push row of a live journal
        that was not itself imported. That row is what makes the journal's
        next edit update its record (and log the 404) rather than post a new
        one, bringing back a record somebody deleted. An imported journal's
        link is kept for the same reason. An echo row, a push row naming an
        imported journal, is deleted: the import's link names its record.

        Sync rows record no user, and each user's sync asks their own Snipe-IT.
        A row another user's live journal holds, by its push or its import
        link, is left to that user's sync. A row no journal holds belongs to
        nobody: every user's inbound sync would import its record as a new
        journal anyway, so forgetting it changes nothing for anyone.

        Only reads are sent to Snipe-IT, so running this again is harmless.

        Args:
            listed_ids: Every maintenance id a completed listing returned.
            session_factory: Factory for database sessions.

        Returns:
            How many sync rows were deleted.

        Raises:
            SnipeItAPIError: If Snipe-IT rejected the API key.
            SnipeItRateLimitError: If Snipe-IT rate limited a lookup.
        """
        listed = set(listed_ids)
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT m.external_id
                    FROM sync_metadata m
                    WHERE m.integration_source = 'snipeit_maintenance'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM journals j
                          WHERE j.user_id <> :user_id
                            AND (
                                j.id = CASE
                                    WHEN m.internal_uuid ~ '^[0-9]+$'
                                    THEN CAST(m.internal_uuid AS bigint)
                                END
                                OR EXISTS (
                                    SELECT 1
                                    FROM journal_external_event_links l
                                    WHERE l.journal_id = j.id
                                      AND l.calendar_id = :calendar_id
                                      AND l.external_event_id = m.external_id
                                )
                            )
                      )
                """),
                {
                    "user_id": self._user_id,
                    "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                },
            )
            candidates = [
                (row.external_id, maintenance_id)
                for row in result.fetchall()
                if (maintenance_id := _snipeit_maintenance_id(row.external_id))
                is not None
                and maintenance_id not in listed
            ]

        deleted = 0
        for external_id, maintenance_id in candidates:
            try:
                exists = await self._api_client.maintenance_exists(maintenance_id)
            except SnipeItAPIError as exc:
                if exc.status_code == 401:
                    raise
                logger.warning(
                    "Could not check a Snipe-IT maintenance missing from the listing",
                    maintenance_id=maintenance_id,
                    status_code=exc.status_code,
                )
                continue
            except httpx.HTTPError:
                logger.warning(
                    "Could not check a Snipe-IT maintenance missing from the listing",
                    maintenance_id=maintenance_id,
                    exc_info=True,
                )
                continue
            if exists:
                continue
            if await self._forget_deleted_maintenance(external_id, session_factory):
                deleted += 1

        logger.info(
            "Reconciled Snipe-IT maintenances missing from the listing",
            checked=len(candidates),
            deleted=deleted,
        )
        return deleted

    async def _forget_deleted_maintenance(
        self, external_id: str, session_factory: Any
    ) -> bool:
        """Delete a gone record's sync row unless a user's journal pushed it.

        Returns whether a row was deleted.
        """
        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("""
                        DELETE FROM sync_metadata m
                        WHERE m.integration_source = 'snipeit_maintenance'
                          AND m.external_id = :external_id
                          AND NOT EXISTS (
                              SELECT 1
                              FROM journals j
                              WHERE j.id = CASE
                                      WHEN m.internal_uuid ~ '^[0-9]+$'
                                      THEN CAST(m.internal_uuid AS bigint)
                                  END
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM journal_external_event_links l
                                    WHERE l.journal_id = j.id
                                      AND l.calendar_id = :calendar_id
                                )
                          )
                        RETURNING m.id
                    """),
                    {
                        "external_id": external_id,
                        "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                    },
                )
                forgotten = result.fetchone() is not None
        if forgotten:
            logger.info(
                "Forgot a Snipe-IT maintenance deleted in Snipe-IT",
                external_id=external_id,
            )
        return forgotten

    async def _sync_single_maintenance(
        self,
        maintenance_id: int,
        session_factory: Any,
    ) -> None:
        """Fetch, transform, and create an outbox event for a maintenance record.

        1. Fetch maintenance from the API.
        2. Look up the internal gear_item_id from sync_metadata for the asset.
        3. Transform into journal data.
        4. Check for existing sync_metadata (dedup via version_hash).
        5. Create outbox event (journal_event.created or .updated).
        6. Update sync_metadata.
        """
        external_id = f"snipeit_maint:{maintenance_id}"

        maintenance = await self._api_client.get_maintenance(maintenance_id)
        if await self._link_claimed_maintenance(maintenance, session_factory):
            raise _MaintenanceSkipped

        async with session_factory() as session:
            async with session.begin():
                # Look up internal gear_item_id for this asset
                if maintenance.asset_id is None:
                    logger.warning(
                        "Skipping maintenance: no asset_id in API response",
                        maintenance_id=maintenance_id,
                    )
                    raise _MaintenanceSkipped
                asset_external_id = str(maintenance.asset_id)
                asset_result = await session.execute(
                    text("""
                        SELECT internal_uuid
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit'
                          AND external_id = :external_id
                    """),
                    {"external_id": asset_external_id},
                )
                asset_meta = asset_result.fetchone()

                if not asset_meta or not asset_meta.internal_uuid:
                    logger.warning(
                        "Skipping maintenance: gear item not yet synced",
                        maintenance_id=maintenance_id,
                        asset_id=maintenance.asset_id,
                    )
                    raise _MaintenanceSkipped

                gear_item_id = str(asset_meta.internal_uuid)
                # A push writing this record's sync row commits it first.
                await _lock_asset_maintenances(session, maintenance.asset_id)

                # Imported dates are local midnights in the owner's zone, the
                # zone a push reads them back in (imports record no event zone).
                zone_result = await session.execute(
                    text("SELECT timezone FROM user_settings WHERE user_id = :user_id"),
                    {"user_id": self._user_id},
                )

                # Transform
                transformer = SnipeItMaintenanceTransformer()
                transformed = transformer.transform(
                    maintenance,
                    user_id=self._user_id,
                    gear_item_id=gear_item_id,
                    zone=_resolve_zone(zone_result.scalar_one_or_none()),
                )

                # Check existing metadata for dedup
                meta_result = await session.execute(
                    text("""
                        SELECT version_hash, internal_uuid,
                               EXTRACT(EPOCH FROM now() - last_synced_at)
                                   AS age_seconds
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_maintenance'
                          AND external_id = :external_id
                        FOR UPDATE
                    """),
                    {"external_id": external_id},
                )
                existing_meta = meta_result.fetchone()

                # Look up existing journal via external event links
                # (populated by JournalOutboxEventProcessor on creation).
                # Read before the hash is compared, because an unchanged record
                # is only uninteresting while a journal still holds it: one
                # whose journal has gone was skipped here on every sync, leaving
                # it in Snipe-IT and invisible in the app with nothing to say so.
                existing_journal_id: int | None = None
                if existing_meta:
                    link_result = await session.execute(
                        text("""
                            SELECT journal_id
                            FROM journal_external_event_links
                            WHERE external_event_id = :external_event_id
                              AND calendar_id = :calendar_id
                            LIMIT 1
                        """),
                        {
                            "external_event_id": external_id,
                            "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                        },
                    )
                    link_row = link_result.fetchone()
                    existing_journal_id = link_row.journal_id if link_row else None

                if (
                    existing_meta
                    and existing_journal_id is not None
                    and existing_meta.version_hash == transformed.version_hash
                ):
                    logger.debug(
                        "Skipping unchanged Snipe-IT maintenance",
                        maintenance_id=maintenance_id,
                    )
                    raise _MaintenanceSkipped

                if (
                    existing_meta
                    and existing_journal_id is None
                    and existing_meta.internal_uuid
                ):
                    # Only a push records the journal, so this record was
                    # created from that user's journal rather than imported —
                    # unless that journal is gone. Deleting a maintenance
                    # journal now deletes its record, but a row orphaned before
                    # that, or by a push that raced a deletion, would hide its
                    # record here for good. It is imported instead, and the row
                    # stops naming the journal that no longer exists.
                    if await _journal_exists(session, int(existing_meta.internal_uuid)):
                        logger.debug(
                            "Skipping Snipe-IT maintenance pushed from a journal",
                            maintenance_id=maintenance_id,
                            journal_id=existing_meta.internal_uuid,
                        )
                        raise _MaintenanceSkipped

                    logger.info(
                        "Importing a Snipe-IT maintenance whose journal was deleted",
                        maintenance_id=maintenance_id,
                        journal_id=existing_meta.internal_uuid,
                    )
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET internal_uuid = NULL
                            WHERE integration_source = 'snipeit_maintenance'
                              AND external_id = :external_id
                        """),
                        {"external_id": external_id},
                    )
                elif existing_meta and existing_journal_id is None:
                    # No link, and no journal named: either the create event
                    # this row's import enqueued has not been turned into a
                    # link yet, or the journal it was turned into has since
                    # been deleted, taking the link with it. The row looks the
                    # same, so they are told apart by how long it has waited.
                    if not _unanswered_create_has_expired(existing_meta):
                        # Still plausibly in flight, so there is no journal to
                        # update yet. An unchanged record can simply wait; for a
                        # changed one, sending another create now would only
                        # race the one the backend is about to answer, so fail
                        # the record and let the next sync look again.
                        if existing_meta.version_hash == transformed.version_hash:
                            logger.debug(
                                "Skipping unchanged Snipe-IT maintenance "
                                "whose create is still pending",
                                maintenance_id=maintenance_id,
                            )
                            raise _MaintenanceSkipped
                        raise RuntimeError(
                            "Outbox creation event pending, cannot update yet"
                        )

                    # Long past that. Whatever became of the create, nothing in
                    # the app holds this record any more, so it is imported as
                    # a new journal rather than failing on every sync for ever.
                    logger.warning(
                        "Importing a Snipe-IT maintenance whose create was never "
                        "answered with a journal",
                        maintenance_id=maintenance_id,
                        age_seconds=existing_meta.age_seconds,
                    )

                # Determine sync action
                sync_action = "updated" if existing_journal_id else "created"

                # Enrich journal_data with gear_maintenance_data and
                # journal_types for the outbox event processor
                journal_data = dict(transformed.journal_data)
                gear_maintenance_data = dict(transformed.gear_maintenance_data)
                if existing_journal_id is not None:
                    type_result = await session.execute(
                        text("""
                            SELECT maintenance_type
                            FROM journal_gear_maintenance_data
                            WHERE journal_id = :journal_id
                        """),
                        {"journal_id": existing_journal_id},
                    )
                    gear_maintenance_data["maintenance_type"] = (
                        SnipeItMaintenanceTransformer.resolve_inbound_maintenance_type(
                            maintenance.asset_maintenance_type,
                            existing_type=type_result.scalar_one_or_none(),
                        )
                    )
                journal_data["gear_maintenance_data"] = gear_maintenance_data
                journal_data["journal_types"] = ["GEAR_MAINTENANCE"]
                journal_data["version_hash"] = transformed.version_hash

                # Build calendar_info_data
                calendar_info_data: dict[str, Any] = {
                    "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                }

                # Create outbox event
                from core_shared.models.outbox import OutboxEvent

                event = OutboxEvent.create_journal_sync_event(
                    journal_data=journal_data,
                    calendar_info_data=calendar_info_data,
                    integration_source=INBOUND_SYNC_CHANGED_BY,
                    external_event_id=external_id,
                    calendar_id=_SNIPEIT_MAINTENANCE_CALENDAR_ID,
                    sync_action=sync_action,
                    existing_journal_id=existing_journal_id,
                )
                session.add(event)

                # Upsert sync_metadata
                await session.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (integration_source, external_id, last_synced_at,
                             version_hash, sync_status, error_message,
                             retry_count, created_at, updated_at)
                        VALUES
                            ('snipeit_maintenance', :external_id, now(),
                             :version_hash, 'success', NULL, 0,
                             now(), now())
                        ON CONFLICT (integration_source, external_id)
                        DO UPDATE SET
                            last_synced_at = EXCLUDED.last_synced_at,
                            version_hash = EXCLUDED.version_hash,
                            sync_status = EXCLUDED.sync_status,
                            error_message = EXCLUDED.error_message,
                            retry_count = 0,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {
                        "external_id": external_id,
                        "version_hash": transformed.version_hash,
                    },
                )

        logger.info(
            "Created outbox event for Snipe-IT maintenance",
            maintenance_id=maintenance_id,
            sync_action=sync_action,
        )

    # -- Outbound Maintenance Sync Methods ----------------------------------

    async def _fetch_maintenance_push_context(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> MaintenancePushContext | None:
        """Fetch what an outbound push of a GEAR_MAINTENANCE journal needs.

        Returns ``None`` when the push must be skipped (logged) because a
        prerequisite is missing. A journal imported from Snipe-IT carries the
        external id of the record it was imported from.
        """
        async with session_factory() as session:
            # 1. Get journal data
            journal_row = await _fetch_journal_row(session, journal_id)
            if not journal_row:
                logger.debug(
                    "Skipping outbound maintenance push: journal not found",
                    journal_id=journal_id,
                )
                return None

            # 2. Get gear maintenance data
            maint_result = await session.execute(
                text("""
                    SELECT gear_item_id, maintenance_type
                    FROM journal_gear_maintenance_data
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            maintenance_data_row = maint_result.fetchone()
            if not maintenance_data_row:
                logger.debug(
                    "Skipping outbound maintenance push: no gear maintenance data",
                    journal_id=journal_id,
                )
                return None

            # 3. Get asset sync metadata (gear_item → Snipe-IT asset ID)
            gear_item_id = str(maintenance_data_row.gear_item_id)
            asset_meta_result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :gear_item_id
                """),
                {"gear_item_id": gear_item_id},
            )
            asset_sync_meta_row = asset_meta_result.fetchone()
            if not asset_sync_meta_row:
                logger.debug(
                    "Skipping outbound maintenance push: gear item not synced to Snipe-IT",
                    journal_id=journal_id,
                    gear_item_id=gear_item_id,
                )
                return None

            # 4. An import already is a Snipe-IT record: the one its link names
            link_result = await session.execute(
                text("""
                    SELECT external_event_id
                    FROM journal_external_event_links
                    WHERE journal_id = :journal_id
                      AND calendar_id = :calendar_id
                    LIMIT 1
                """),
                {
                    "journal_id": journal_id,
                    "calendar_id": _SNIPEIT_MAINTENANCE_CALENDAR_ID,
                },
            )
            link_row = link_result.fetchone()
            imported_external_id = link_row.external_event_id if link_row else None

        return MaintenancePushContext(
            journal=journal_row,
            maintenance=maintenance_data_row,
            asset_meta=asset_sync_meta_row,
            imported_external_id=imported_external_id,
        )

    async def push_maintenance_create(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push a new GEAR_MAINTENANCE journal to Snipe-IT as a maintenance record.

        The record is claimed on the journal's claim row before it is posted,
        and the claim is replaced by the record's sync row once it is recorded.
        An attempt that fails in between leaves its claim marked failed: the
        record may exist even though its response was lost.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.

        Raises:
            SnipeItSyncInProgress: Another worker's attempt to create this
                journal's record is still in flight; the event is redelivered.
        """
        context = await self._fetch_maintenance_push_context(
            journal_id, session_factory
        )
        if context is None:
            return
        if context.imported_external_id is not None:
            # Creating a record for an import would copy the record it already is
            logger.debug(
                "Skipping outbound maintenance create: journal was imported from Snipe-IT",
                journal_id=journal_id,
                external_id=context.imported_external_id,
            )
            return

        payload = context.snipeit_payload()

        try:
            snipeit_asset_id = int(context.asset_meta.external_id)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid asset sync metadata external_id",
                external_id=context.asset_meta.external_id,
                journal_id=journal_id,
            )
            return

        claim = MaintenanceClaim.for_payload(snipeit_asset_id, payload)
        version_hash = _payload_version_hash(payload)

        # A redelivered event for a journal already recorded only brings its
        # record up to date: searching Snipe-IT again could only fail it.
        if await self._update_recorded_maintenance(
            journal_id, version_hash, session_factory
        ):
            logger.debug(
                "Skipping maintenance create: already synced to Snipe-IT",
                journal_id=journal_id,
            )
            return

        # A failed attempt's record carries what was sent then, which an edit
        # since may have changed; one on another asset is not this record.
        async with session_factory() as session:
            earlier_row = await _fetch_maintenance_claim(session, journal_id)
        _raise_if_claim_in_flight(journal_id, earlier_row)
        earlier_claim = (
            MaintenanceClaim.from_reference(earlier_row.reference_data)
            if earlier_row
            else None
        )
        candidates = await self._maintenance_candidates(
            snipeit_asset_id,
            [
                candidate_claim
                for candidate_claim in (claim, earlier_claim)
                if candidate_claim is not None
                and candidate_claim.asset_id == snipeit_asset_id
            ],
        )

        outcome = await self._claim_maintenance(
            journal_id, claim, candidates, session_factory
        )
        if outcome == "journal_gone":
            logger.info(
                "Journal deleted before its maintenance was posted",
                journal_id=journal_id,
            )
            return
        if outcome != "claimed":
            await self._update_recorded_maintenance(
                journal_id, version_hash, session_factory
            )
            return

        try:
            created = await self._api_client.create_maintenance(
                asset_id=snipeit_asset_id,
                payload=payload,
            )
            journal_gone = await self._record_pushed_maintenance(
                journal_id,
                claim,
                f"snipeit_maint:{created.id}",
                version_hash,
                session_factory,
            )
            if journal_gone:
                # The deletion handler looked for this journal's rows before
                # there were any, so nothing else will remove the record.
                await self._api_client.delete_maintenance(created.id)
                return
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT maintenance create failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                await self._release_maintenance_claim(journal_id, session_factory)
                return
            await self._fail_maintenance_claim(journal_id, session_factory, str(exc))
            raise
        except Exception as exc:
            await self._fail_maintenance_claim(journal_id, session_factory, str(exc))
            raise

        logger.info(
            "Successfully pushed new maintenance to Snipe-IT",
            journal_id=journal_id,
            snipeit_maintenance_id=created.id,
        )

    async def _update_recorded_maintenance(
        self, journal_id: int, version_hash: str, session_factory: Any
    ) -> bool:
        """Send the journal's values to its recorded record when it holds others.

        Returns ``False`` when the journal has no recorded record.

        A linked record keeps what its creator sent: a failed attempt's values
        from before an edit, or a record entered by hand. An edit made while the
        journal had no sync row was never sent. The push row's hash says what
        the record holds, and the update records the journal's hash only once it
        lands, so a failed update is retried with the redelivered event.
        """
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT version_hash
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_maintenance'
                      AND internal_uuid = :journal_id
                    LIMIT 1
                """),
                {"journal_id": str(journal_id)},
            )
            recorded_hash = result.scalar_one_or_none()
        if recorded_hash is None:
            return False
        if recorded_hash != version_hash:
            await self.push_maintenance_update(journal_id, session_factory)
        return True

    async def _maintenance_candidates(
        self, asset_id: int, claims: Sequence[MaintenanceClaim]
    ) -> list[SnipeItMaintenance]:
        """Page the asset's Snipe-IT maintenances for records any of ``claims`` match.

        Linking is best-effort: when this API key may not read the list, nothing
        is linked and the record is posted as usual.
        """
        candidates: list[SnipeItMaintenance] = []
        try:
            for page in range(1, _MAINTENANCE_MAX_PAGES + 1):
                response = await self._api_client.list_maintenances(
                    asset_id=asset_id, page=page, per_page=_PAGE_SIZE
                )
                candidates.extend(
                    maintenance
                    for maintenance in response.rows
                    if any(claim.matches(maintenance) for claim in claims)
                )
                if (
                    len(response.rows) < _PAGE_SIZE
                    or page * _PAGE_SIZE >= response.total
                ):
                    break
            else:
                logger.warning(
                    "Stopped searching Snipe-IT maintenances at the page limit",
                    snipeit_asset_id=asset_id,
                )
        except SnipeItAPIError as exc:
            if exc.status_code not in (403, 404):
                raise
            logger.warning(
                "Snipe-IT maintenance list unavailable; creating without linking",
                snipeit_asset_id=asset_id,
                status_code=exc.status_code,
            )
            return []
        return candidates

    async def _user_maintenance_claims(
        self, session: Any
    ) -> list[tuple[int, MaintenanceClaim]]:
        """Every live claim of this user's journals, with the journal it belongs to.

        Maintenance ids are unique only within one Snipe-IT instance, so other
        users' claims never count. A deleted journal's claim is ignored, and so
        is a claim whose journal already has its record: it is spent, and must
        not link a second record to that journal. A claim made for an asset the
        journal has since moved from is ignored too, as the push ignores it: the
        record it describes is on the wrong gear to be the journal's.
        """
        rows = await session.execute(
            text("""
                SELECT j.id AS journal_id, sm.reference_data,
                       asset.external_id AS asset_external_id
                FROM sync_metadata sm
                JOIN journals j ON j.id::text = sm.internal_uuid
                JOIN journal_gear_maintenance_data gm ON gm.journal_id = j.id
                JOIN sync_metadata asset
                    ON asset.integration_source = 'snipeit'
                   AND asset.internal_uuid = gm.gear_item_id::text
                WHERE sm.integration_source = :claim_source
                  AND j.user_id = :user_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM sync_metadata recorded
                      WHERE recorded.integration_source = 'snipeit_maintenance'
                        AND recorded.internal_uuid = sm.internal_uuid
                  )
            """),
            {"claim_source": _MAINTENANCE_CLAIM_SOURCE, "user_id": self._user_id},
        )
        return [
            (row.journal_id, claim)
            for row in rows.fetchall()
            if (claim := MaintenanceClaim.from_reference(row.reference_data))
            and str(claim.asset_id) == row.asset_external_id
        ]

    async def _link_claimed_maintenance(
        self, maintenance: SnipeItMaintenance, session_factory: Any
    ) -> bool:
        """Record an unrecorded Snipe-IT maintenance as the journal whose push claims it.

        A push claims its record before posting it, so a record whose response
        was lost, or that a sync fetches before the push records it, is found
        here rather than imported as a second journal. A record several of this
        user's claims match is left alone: any of those journals' attempts may
        have created it, and a later sync looks again.

        Returns:
            ``True`` when the record must not be imported.
        """
        if maintenance.asset_id is None:
            return False
        external_id = f"snipeit_maint:{maintenance.id}"
        async with session_factory() as session:
            async with session.begin():
                await _lock_asset_maintenances(session, maintenance.asset_id)
                recorded = await session.execute(
                    text("""
                        SELECT 1
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_maintenance'
                          AND external_id = :external_id
                    """),
                    {"external_id": external_id},
                )
                if recorded.fetchone():
                    return False
                claimants = [
                    journal_id
                    for journal_id, claim in await self._user_maintenance_claims(
                        session
                    )
                    if claim.matches(maintenance)
                ]
                if not claimants:
                    return False
                if len(claimants) > 1:
                    logger.warning(
                        "Leaving a Snipe-IT maintenance several journals' pushes claim",
                        maintenance_id=maintenance.id,
                        journal_ids=claimants,
                    )
                    return True
                [journal_id] = claimants
                # Sync rows are keyed globally, so another user's sync may have
                # recorded this maintenance id under another asset's lock; the
                # journal then keeps its claim.
                if (
                    await _insert_push_row(
                        session,
                        journal_id,
                        external_id,
                        _payload_version_hash(_snipeit_record_payload(maintenance)),
                    )
                    != "inserted"
                ):
                    return False
                await _delete_maintenance_claim(session, journal_id)
        logger.info(
            "Linked a Snipe-IT maintenance to the journal whose push created it",
            maintenance_id=maintenance.id,
            journal_id=journal_id,
        )
        return True

    async def _free_maintenance(
        self,
        session: Any,
        journal_id: int,
        candidates: Sequence[SnipeItMaintenance],
    ) -> SnipeItMaintenance | None:
        """The first candidate no other journal holds, or ``None``.

        A record is held when any sync row names it: another journal's push, or
        an import, which belongs to its imported journal. It is also held when it
        matches another of this user's journals' claims, since that journal's
        failed attempt may have created it.
        """
        if not candidates:
            return None
        rows = await session.execute(
            text("""
                SELECT external_id
                FROM sync_metadata
                WHERE integration_source = 'snipeit_maintenance'
                  AND external_id = ANY(:external_ids)
            """),
            {"external_ids": [f"snipeit_maint:{m.id}" for m in candidates]},
        )
        recorded = {row.external_id for row in rows.fetchall()}
        other_claims = [
            claim
            for claimant, claim in await self._user_maintenance_claims(session)
            if claimant != journal_id
        ]
        return next(
            (
                maintenance
                for maintenance in candidates
                if f"snipeit_maint:{maintenance.id}" not in recorded
                and not any(other.matches(maintenance) for other in other_claims)
            ),
            None,
        )

    async def _claim_maintenance(
        self,
        journal_id: int,
        claim: MaintenanceClaim,
        candidates: Sequence[SnipeItMaintenance],
        session_factory: Any,
    ) -> Literal["recorded", "linked", "claimed", "journal_gone"]:
        """Link a free candidate, or else claim the record about to be posted.

        Runs under the asset's lock, so journals processed at once see each
        other's claims and sync rows.

        Returns:
            ``"recorded"`` when the journal's record already has its sync row,
            ``"linked"`` when a candidate was recorded as its record,
            ``"claimed"`` when the claim is written and the record is to be
            posted, and ``"journal_gone"`` when the journal was deleted while
            this push was running, so nothing is to be posted or linked.

        Raises:
            SnipeItSyncInProgress: The journal's claim is still in flight.
        """
        async with session_factory() as session:
            async with session.begin():
                await _lock_asset_maintenances(session, claim.asset_id)
                if await _recorded_maintenance(session, journal_id) is not None:
                    return "recorded"
                if not await _journal_exists(session, journal_id, lock=True):
                    # Deleted since this push read it. Neither claiming nor
                    # linking is right: a record posted now belongs to nothing,
                    # and one whose response is lost leaves nothing to clean up.
                    await _delete_maintenance_claim(session, journal_id)
                    return "journal_gone"
                _raise_if_claim_in_flight(
                    journal_id, await _fetch_maintenance_claim(session, journal_id)
                )

                free = await self._free_maintenance(session, journal_id, candidates)
                if (
                    free is not None
                    and await _insert_push_row(
                        session,
                        journal_id,
                        f"snipeit_maint:{free.id}",
                        _payload_version_hash(_snipeit_record_payload(free)),
                    )
                    == "inserted"
                ):
                    await _delete_maintenance_claim(session, journal_id)
                    logger.info(
                        "Linked an existing Snipe-IT maintenance instead of creating one",
                        journal_id=journal_id,
                        snipeit_maintenance_id=free.id,
                    )
                    return "linked"

                await session.execute(
                    text("""
                        INSERT INTO sync_metadata
                            (internal_uuid, integration_source, external_id,
                             last_synced_at, version_hash, sync_status,
                             error_message, retry_count, reference_data,
                             created_at, updated_at)
                        VALUES
                            (:journal_id, :claim_source, :journal_id,
                             now(), 'PENDING', 'pending',
                             NULL, 0, :reference_data,
                             now(), now())
                        ON CONFLICT (integration_source, external_id)
                        DO UPDATE SET
                            sync_status = 'pending',
                            error_message = NULL,
                            reference_data = EXCLUDED.reference_data,
                            updated_at = now()
                    """),
                    {
                        "claim_source": _MAINTENANCE_CLAIM_SOURCE,
                        "journal_id": str(journal_id),
                        "reference_data": claim.to_reference(),
                    },
                )
        return "claimed"

    async def _record_pushed_maintenance(
        self,
        journal_id: int,
        claim: MaintenanceClaim,
        external_id: str,
        version_hash: str,
        session_factory: Any,
    ) -> bool:
        """Replace the journal's claim with the sync row of the record it posted.

        The inbound sync may have recorded the journal's record while the POST
        was in flight. When that is another record (one this push's search
        missed), the posted one is reported rather than recorded twice.

        A record's row is never re-pointed. Sync rows are not scoped to a user,
        so another user's Snipe-IT can hold the same maintenance id; that row is
        left alone and reported, and the journal keeps its claim.

        Returns:
            ``True`` when the journal was deleted while its POST was in flight,
            so the record it created belongs to nothing and must be deleted.
            Its claim is dropped here: a claim outlives its journal no better
            than a push row does.
        """
        async with session_factory() as session:
            async with session.begin():
                await _lock_asset_maintenances(session, claim.asset_id)
                linked = await _recorded_maintenance(session, journal_id)
                if linked is not None:
                    if linked != external_id:
                        logger.warning(
                            "Created a Snipe-IT maintenance for a journal already "
                            "linked to another; the new record will import as a "
                            "separate journal",
                            journal_id=journal_id,
                            external_id=external_id,
                            linked_external_id=linked,
                        )
                    return False
                outcome = await _insert_push_row(
                    session, journal_id, external_id, version_hash
                )
                if outcome == "journal_gone":
                    logger.info(
                        "Journal deleted while its maintenance was being posted",
                        journal_id=journal_id,
                        external_id=external_id,
                    )
                    await _delete_maintenance_claim(session, journal_id)
                    return True
                if outcome == "taken":
                    logger.error(
                        "Posted Snipe-IT maintenance already has a sync row",
                        journal_id=journal_id,
                        external_id=external_id,
                    )
                    return False
                await _delete_maintenance_claim(session, journal_id)
        return False

    async def _release_maintenance_claim(
        self, journal_id: int, session_factory: Any
    ) -> None:
        """Remove the journal's claim once its record will not be created."""
        async with session_factory() as session:
            async with session.begin():
                await _delete_maintenance_claim(session, journal_id)

    async def _fail_maintenance_claim(
        self, journal_id: int, session_factory: Any, error_message: str
    ) -> None:
        """Mark the journal's claim failed, so its retry need not wait for it.

        The claim itself stays: the failed attempt may have created the record.
        """
        try:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'failed',
                                error_message = :error_message,
                                updated_at = now()
                            WHERE integration_source = :claim_source
                              AND external_id = :journal_id
                        """),
                        {
                            "claim_source": _MAINTENANCE_CLAIM_SOURCE,
                            "journal_id": str(journal_id),
                            "error_message": error_message[:255],
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to mark maintenance claim failed",
                journal_id=journal_id,
                error=str(exc),
            )

    async def push_maintenance_update(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push an updated GEAR_MAINTENANCE journal to Snipe-IT.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.
        """
        context = await self._fetch_maintenance_push_context(
            journal_id, session_factory
        )
        if context is None:
            return

        # An import updates the record it was imported from, even when an earlier
        # echo left a push row naming a copy of it
        external_id = context.imported_external_id
        if external_id is None:
            async with session_factory() as session:
                maint_meta_result = await session.execute(
                    text("""
                        SELECT external_id
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_maintenance'
                          AND internal_uuid = :journal_id
                    """),
                    {"journal_id": str(journal_id)},
                )
                maint_sync_row = maint_meta_result.fetchone()
            external_id = maint_sync_row.external_id if maint_sync_row else None

        if external_id is None:
            logger.debug(
                "Skipping outbound maintenance update: no sync metadata",
                journal_id=journal_id,
            )
            return

        snipeit_maintenance_id = _snipeit_maintenance_id(external_id)
        if snipeit_maintenance_id is None:
            logger.warning(
                "Invalid maintenance sync metadata external_id",
                external_id=external_id,
                journal_id=journal_id,
            )
            return

        payload = context.snipeit_payload()

        # PATCH the Snipe-IT maintenance record
        try:
            await self._api_client.update_maintenance(snipeit_maintenance_id, payload)
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT maintenance update failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_maintenance_id=snipeit_maintenance_id,
                    status_code=exc.status_code,
                )
                return
            raise

        # A push row records what was pushed. An import has none: its sync row
        # tracks the record as fetched, and the next inbound sync refreshes it.
        if context.imported_external_id is None:
            version_hash = _payload_version_hash(payload)
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET version_hash = :version_hash,
                                last_synced_at = now(),
                                updated_at = now()
                            WHERE integration_source = 'snipeit_maintenance'
                              AND internal_uuid = :journal_id
                        """),
                        {
                            "version_hash": version_hash,
                            "journal_id": str(journal_id),
                        },
                    )

        logger.info(
            "Successfully pushed maintenance update to Snipe-IT",
            journal_id=journal_id,
            snipeit_maintenance_id=snipeit_maintenance_id,
        )

    async def delete_pushed_maintenance(
        self, journal_id: int, session_factory: Any
    ) -> bool:
        """Delete the Snipe-IT maintenance a now-deleted journal pushed.

        Snipe-IT keeps whatever it is not told to remove, and the inbound sync
        would import a record no journal holds as a new journal — so leaving the
        record behind would undo the deletion. The journal's sync rows go with
        it: the push row that named the record, and the claim an attempt that
        failed after posting may have left.

        The journal itself is already gone, so the record is resolved from its
        push row rather than from the journal. This is a no-op for a journal
        that never reached Snipe-IT.

        A journal deleted with only a claim posts nothing: whether its lost POST
        created a record is unknowable, and matching one by title and date could
        delete a record somebody entered by hand. Such a record still imports as
        a new journal, which Part 3 of the specification records as a known gap.

        Args:
            journal_id: The deleted journal.
            session_factory: Factory for database sessions.

        Returns:
            ``True`` when the record is gone from Snipe-IT, whether this call
            deleted it or found it already deleted.

        Raises:
            SnipeItAPIError: If Snipe-IT could not be reached or refused the
                delete for a reason worth retrying the event for.
        """
        async with session_factory() as session:
            external_id = await _recorded_maintenance(session, journal_id)

        if external_id is None:
            # No record to delete: an unsynced journal, or one whose push never
            # got past its claim. Either way the claim is inert now.
            await self._release_maintenance_claim(journal_id, session_factory)
            logger.debug(
                "Deleted journal had no Snipe-IT maintenance",
                journal_id=journal_id,
            )
            return False

        deleted = await self.delete_maintenance_record(
            external_id=external_id, session_factory=session_factory
        )
        if deleted:
            await self._release_maintenance_claim(journal_id, session_factory)
        return deleted

    async def delete_maintenance_record(
        self, external_id: str, session_factory: Any
    ) -> bool:
        """Delete the Snipe-IT maintenance ``external_id`` names, and its sync row.

        The one way a record is removed, whichever kind of journal asked for it.
        A journal reaches its record by two different routes — a pushed one
        through the sync row that names the journal, an imported one through the
        external id its deletion event carries, since an import's row names no
        journal — but what has to happen to the record is the same, so they meet
        here rather than each doing it their own way.

        Args:
            external_id: The record's ``snipeit_maint:{id}`` sync key.
            session_factory: Factory for database sessions.

        Returns:
            ``True`` when the record is gone from Snipe-IT, whether this call
            deleted it or found it already deleted.

        Raises:
            SnipeItAPIError: If Snipe-IT could not be reached or refused the
                delete for a reason worth retrying the event for.
        """
        snipeit_maintenance_id = _snipeit_maintenance_id(external_id)
        if snipeit_maintenance_id is None:
            logger.warning(
                "Invalid maintenance sync metadata external_id",
                external_id=external_id,
            )
            return False

        async with session_factory() as session:
            holder = await _journal_holding_maintenance(session, external_id)
        if holder is not None:
            # Someone holds this record now, so the deletion being processed is
            # not about it: a redelivered event, or one that crossed a sync that
            # imported the record again. Deleting it would take a live journal's
            # record away.
            logger.info(
                "Not deleting a Snipe-IT maintenance a live journal holds",
                external_id=external_id,
                journal_id=holder,
            )
            return False

        try:
            await self._api_client.delete_maintenance(snipeit_maintenance_id)
        except SnipeItAPIError as exc:
            if exc.status_code == 403:
                # The record is still there, so its row stays with it. It is not
                # lost: no journal holds it any more, so the next full sync
                # imports it as a new journal rather than skipping it.
                logger.warning(
                    "Snipe-IT maintenance delete forbidden; keeping its sync row",
                    external_id=external_id,
                    snipeit_maintenance_id=snipeit_maintenance_id,
                    status_code=exc.status_code,
                )
                return False
            raise

        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        DELETE FROM sync_metadata
                        WHERE integration_source = 'snipeit_maintenance'
                          AND external_id = :external_id
                    """),
                    {"external_id": external_id},
                )

        logger.info(
            "Deleted the Snipe-IT maintenance of a deleted journal",
            external_id=external_id,
            snipeit_maintenance_id=snipeit_maintenance_id,
        )
        return True

    # -- Outbound Checkout Sync Methods -------------------------------------

    async def _fetch_journal_and_gear_usage_data(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> tuple[Any, Any, Any] | None:
        """Fetch journal, gear-usage, and asset-sync data for outbound checkout.

        Returns a ``(journal_row, usage_data_row, asset_sync_meta_row)``
        tuple, or ``None`` if any prerequisite is missing (logged and skipped).
        """
        async with session_factory() as session:
            # 1. Get journal data
            journal_row = await _fetch_journal_row(session, journal_id)
            if not journal_row:
                logger.debug(
                    "Skipping outbound checkout push: journal not found",
                    journal_id=journal_id,
                )
                return None

            # 2. Get gear usage data
            usage_result = await session.execute(
                text("""
                    SELECT gear_item_id, checkout_date, checkin_date
                    FROM journal_gear_usage_data
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            usage_data_row = usage_result.fetchone()
            if not usage_data_row:
                logger.debug(
                    "Skipping outbound checkout push: no gear usage data",
                    journal_id=journal_id,
                )
                return None

            # 3. Get asset sync metadata (gear_item → Snipe-IT asset ID)
            gear_item_id = str(usage_data_row.gear_item_id)
            asset_meta_result = await session.execute(
                text("""
                    SELECT external_id
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit'
                      AND internal_uuid = :gear_item_id
                """),
                {"gear_item_id": gear_item_id},
            )
            asset_sync_meta_row = asset_meta_result.fetchone()
            if not asset_sync_meta_row:
                logger.debug(
                    "Skipping outbound checkout push: gear item not synced to Snipe-IT",
                    journal_id=journal_id,
                    gear_item_id=gear_item_id,
                )
                return None

        return journal_row, usage_data_row, asset_sync_meta_row

    async def push_checkout_create(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Push a new GEAR_USAGE journal to Snipe-IT as an asset checkout.

        Args:
            journal_id: Internal journal ID.
            session_factory: Async session factory for DB queries.

        Raises:
            SnipeItSyncInProgress: Another worker holds this journal's checkout;
                the event must be retried once that checkout finishes.
        """
        data = await self._fetch_journal_and_gear_usage_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, usage_data_row, asset_sync_meta_row = data

        if not self._snipeit_user_id:
            logger.warning(
                "Skipping checkout create: snipeit_user_id is not configured",
                journal_id=journal_id,
            )
            return

        try:
            snipeit_asset_id = int(asset_sync_meta_row.external_id)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid asset sync metadata external_id",
                external_id=asset_sync_meta_row.external_id,
                journal_id=journal_id,
            )
            return

        external_id = f"snipeit_checkout:{snipeit_asset_id}:{journal_id}"

        previous_asset_id: int | None = None
        asset_dates_before: AssetUsageDates | None = None

        # Check if already synced and acquire a distributed lock by marking as pending
        async with session_factory() as session:
            async with session.begin():
                checkout_meta_result = await session.execute(
                    text("""
                        SELECT sync_status, external_id, reference_data,
                               extract(epoch from (now() - updated_at)) as age_seconds
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :journal_id
                        FOR UPDATE SKIP LOCKED
                    """),
                    {"journal_id": str(journal_id)},
                )
                row = checkout_meta_result.fetchone()
                if row:
                    if row.sync_status == "success":
                        logger.debug(
                            "Skipping checkout create: already synced to Snipe-IT",
                            journal_id=journal_id,
                        )
                        return
                    if (
                        row.sync_status == "pending"
                        and row.age_seconds is not None
                        and row.age_seconds < IN_FLIGHT_LOCK_SECONDS
                    ):
                        raise SnipeItSyncInProgress(
                            f"Checkout of journal {journal_id} is in flight"
                        )

                    previous_asset_id = _checkout_asset_id(row.external_id)
                    if previous_asset_id == snipeit_asset_id:
                        # A superseded pair on this asset keeps the dates read
                        # before its first checkout: the asset now carries that
                        # pair's dates, not the ones it had before this journal.
                        asset_dates_before = AssetUsageDates.from_reference(
                            row.reference_data
                        )
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'pending', updated_at = now()
                            WHERE integration_source = 'snipeit_checkout' AND internal_uuid = :journal_id
                        """),
                        # The row keeps the previous attempt's asset until that
                        # asset has been dealt with (see below).
                        {"journal_id": str(journal_id)},
                    )
                else:
                    insert_result = await session.execute(
                        text("""
                            INSERT INTO sync_metadata
                                (internal_uuid, integration_source, external_id,
                                 last_synced_at, version_hash, sync_status,
                                 error_message, retry_count, created_at, updated_at)
                            VALUES
                                (:internal_uuid, 'snipeit_checkout', :external_id,
                                 now(), 'PENDING', 'pending', NULL, 0, now(), now())
                            ON CONFLICT (integration_source, external_id) DO NOTHING
                            RETURNING id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                        },
                    )
                    if not insert_result.fetchone():
                        raise SnipeItSyncInProgress(
                            f"Checkout of journal {journal_id} is locked by another worker"
                        )

        # Resolve dates: buffer dates take precedence, fall back to journal range
        checkout_date = (
            usage_data_row.checkout_date or journal_row.event_date_range_start
        )
        checkin_date = usage_data_row.checkin_date or journal_row.event_date_range_end

        if not checkout_date or not checkin_date:
            logger.warning(
                "Missing required dates for gear usage checkout",
                journal_id=journal_id,
                has_checkout=bool(checkout_date),
                has_checkin=bool(checkin_date),
            )
            # Unlock the pending status so it can be retried when data is fixed
            await self._unlock_pending_checkout(
                journal_id, session_factory, "Missing required dates"
            )
            return

        if checkin_date < checkout_date:
            logger.warning(
                "Invalid date range for gear usage checkout: checkin before checkout",
                journal_id=journal_id,
                checkout_date=str(checkout_date),
                checkin_date=str(checkin_date),
            )
            await self._unlock_pending_checkout(
                journal_id, session_factory, "Invalid date range"
            )
            return

        zone = _snipeit_zone(journal_row)
        checkout_at = _format_date_for_snipeit(checkout_date, zone)
        expected_checkin = _format_date_for_snipeit(checkin_date, zone)

        # Build checkout payload. Snipe-IT keeps a checkout's time of day (unlike
        # a check-in's), so send it; the lookup day and recorded date stay dates.
        payload: dict[str, Any] = {
            "assigned_user": self._snipeit_user_id,
            "checkout_to_type": "user",
            "checkout_at": _snipeit_datetime(checkout_date, zone),
            "expected_checkin": expected_checkin,
        }
        if journal_row.title:
            payload["note"] = journal_row.title

        # Link a checkout already in Snipe-IT (e.g. entered by hand before an
        # import) instead of recording it twice; otherwise POST a new one.
        linked_log_id: int | None = None
        snipeit_log_id: int | None = None
        try:
            if previous_asset_id not in (None, snipeit_asset_id):
                await self._return_previous_asset(
                    previous_asset_id,
                    journal_id=journal_id,
                    session_factory=session_factory,
                )
                # Only now may the row forget the previous asset: had the return
                # failed, the retry must still derive it from the row.
                await self._rekey_checkout(journal_id, external_id, session_factory)
            linked_log_id = await self._find_unlinked_activity(
                asset_id=snipeit_asset_id,
                action_type="checkout",
                day=checkout_at,
                source="snipeit_checkout",
                journal_id=journal_id,
                external_id=external_id,
                session_factory=session_factory,
                at=payload["checkout_at"],
            )
            snipeit_log_id = linked_log_id
            if linked_log_id is None:
                if asset_dates_before is None:
                    asset_dates_before = AssetUsageDates.from_asset(
                        await self._api_client.get_asset(snipeit_asset_id)
                    )
                # Kept before posting: a checkout whose response is lost is
                # linked on retry, when the asset already shows its date.
                await self._mark_checkout_posting(
                    journal_id, external_id, asset_dates_before, session_factory
                )
                await self._api_client.checkout_asset(
                    asset_id=snipeit_asset_id,
                    payload=payload,
                )
                # Keep the posted entry's id too, so another usage of the asset
                # that day cannot link it as its own.
                snipeit_log_id = await self._find_unlinked_activity(
                    asset_id=snipeit_asset_id,
                    action_type="checkout",
                    day=checkout_at,
                    source="snipeit_checkout",
                    journal_id=journal_id,
                    external_id=external_id,
                    session_factory=session_factory,
                    at=payload["checkout_at"],
                    exact=True,
                )
        except SnipeItAPIError as exc:
            # Handle 403/404 specific errors gracefully
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT checkout create failed (not found/forbidden)",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                await self._unlock_pending_checkout(
                    journal_id,
                    session_factory,
                    f"API Error {exc.status_code}",
                )
                return

            # For 500s or other errors, unlock and raise so it retries
            await self._unlock_pending_checkout(
                journal_id, session_factory, str(exc)[:255]
            )
            raise
        except Exception as exc:
            await self._unlock_pending_checkout(
                journal_id, session_factory, str(exc)[:255]
            )
            raise

        checkout_reference: dict[str, Any] = {
            "checkout_at": checkout_at,
            "expected_checkin": expected_checkin,
        }
        if snipeit_log_id is not None:
            checkout_reference["snipeit_log_id"] = snipeit_log_id
        if asset_dates_before is not None:
            checkout_reference[_ASSET_DATES_BEFORE] = asset_dates_before.to_reference()

        # Save sync metadata: journal_id → snipeit_checkout
        # Note: Snipe-IT does not support an idempotency key on checkouts.
        # By using a pending lock beforehand, we mitigate concurrent processing double-POSTs.
        version_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = :version_hash,
                            last_synced_at = now(),
                            sync_status = 'success',
                            error_message = NULL,
                            reference_data = :reference_data,
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :internal_uuid
                          AND external_id = :external_id
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "version_hash": version_hash,
                        "reference_data": json.dumps(checkout_reference),
                    },
                )

        logger.info(
            "Successfully pushed checkout to Snipe-IT",
            journal_id=journal_id,
            snipeit_asset_id=snipeit_asset_id,
            linked_snipeit_log_id=linked_log_id,
            snipeit_log_id=snipeit_log_id,
        )

        # If the usage period is already over (e.g. logging a past trip), the
        # asset must not stay checked out — immediately record the check-in.
        if _usage_period_has_ended(checkin_date):
            await self.push_checkin_create(
                journal_id=journal_id,
                session_factory=session_factory,
                note=f"Usage period {checkout_at} to {expected_checkin}",
                checkin_at=_snipeit_checkin_at(_local_date(checkin_date, zone)),
                usage_dates=AssetUsageDates.from_instants(
                    checkout_date, checkin_date, zone
                ),
            )

    async def _return_previous_asset(
        self, asset_id: int | None, *, journal_id: int, session_factory: Any
    ) -> None:
        """Check in an asset an earlier, failed checkout attempt may have checked out.

        A checkout whose response was lost is recorded as failed even though
        Snipe-IT may have checked the asset out. Once the journal moves to another
        gear item that asset would stay out with no sync row left to return it,
        so it is returned first — but only while Snipe-IT shows it checked out to
        the mapped user and no other journal may hold it. A pending or failed
        attempt by another journal counts as holding it, since that attempt may
        have checked the asset out too; leaving it out is recoverable, returning
        an asset still in use is not.
        """
        if asset_id is None:
            return
        try:
            asset = await self._api_client.get_asset(asset_id)
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                return
            raise
        assignee = asset.assigned_to
        if (
            assignee is None
            or assignee.type != "user"
            or str(assignee.id) != str(self._snipeit_user_id)
        ):
            return

        async with session_factory() as session:
            held_elsewhere = await session.execute(
                text("""
                    SELECT 1
                    FROM sync_metadata co
                    LEFT JOIN sync_metadata ci
                        ON ci.integration_source = 'snipeit_checkin'
                        AND ci.internal_uuid = co.internal_uuid
                        AND ci.sync_status = 'success'
                    WHERE co.integration_source = 'snipeit_checkout'
                      AND co.external_id LIKE :asset_prefix
                      AND co.internal_uuid <> :journal_id
                      AND (co.sync_status <> 'success' OR ci.id IS NULL)
                    LIMIT 1
                """),
                {
                    "asset_prefix": f"snipeit_checkout:{asset_id}:%",
                    "journal_id": str(journal_id),
                },
            )
            if held_elsewhere.fetchone():
                return

        await self._api_client.checkin_asset(
            asset_id=asset_id,
            payload={"note": "Gear usage journal moved to another gear item"},
        )
        logger.info(
            "Returned the asset of a superseded checkout attempt",
            journal_id=journal_id,
            snipeit_asset_id=asset_id,
        )

    async def _mark_checkout_posting(
        self,
        journal_id: int,
        external_id: str,
        asset_dates: AssetUsageDates,
        session_factory: Any,
    ) -> None:
        """Mark the in-progress checkout row as posting, with the asset's dates before.

        Until the posted entry is claimed, another journal's link waits for it
        (see :meth:`_claim_activity_log`): that entry cannot be told apart from
        one made by hand.
        """
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET reference_data = :reference_data, updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :internal_uuid
                          AND external_id = :external_id
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "reference_data": json.dumps(
                            {
                                _ASSET_DATES_BEFORE: asset_dates.to_reference(),
                                _POSTING: True,
                            }
                        ),
                    },
                )

    async def _rekey_checkout(
        self, journal_id: int, external_id: str, session_factory: Any
    ) -> None:
        """Point a journal's checkout row at the asset now being checked out."""
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET external_id = :external_id, updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :internal_uuid
                    """),
                    {"internal_uuid": str(journal_id), "external_id": external_id},
                )

    async def _find_unlinked_activity(
        self,
        *,
        asset_id: int,
        action_type: str,
        day: str | None,
        source: str,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        after_log_id: int | None = None,
        at: str | None = None,
        exact: bool = False,
    ) -> int | None:
        """Claim an existing Snipe-IT log entry this journal can link to, if any.

        Candidates are entries dated ``day`` (Snipe-IT's server date) that involve
        the mapped Snipe-IT user, match the wall-clock time ``at`` (see
        :func:`_activity_matches_time`) and, when ``after_log_id`` is given, were
        logged after it; one no other journal holds is claimed on this journal's
        ``source`` row (``external_id``). Linking is best-effort: when the
        activity report cannot be read, nothing is linked and the caller records
        the history as usual.
        """
        if not day or not self._snipeit_user_id:
            return None
        candidates = await self._activity_candidates(
            asset_id=asset_id,
            action_type=action_type,
            day=day,
            after_log_id=after_log_id,
            at=at,
            exact=exact,
        )
        if not candidates:
            return None
        return await self._claim_activity_log(
            candidates,
            source=source,
            asset_id=asset_id,
            journal_id=journal_id,
            external_id=external_id,
            session_factory=session_factory,
            defer_to_posting=not exact,
        )

    async def _activity_candidates(
        self,
        *,
        asset_id: int,
        action_type: str,
        day: str,
        after_log_id: int | None,
        at: str | None,
        exact: bool,
    ) -> list[int]:
        """Page the asset's ``action_type`` activity, newest first, for matches."""
        matches = await self._matching_activity(
            asset_id=asset_id,
            action_type=action_type,
            matches=lambda activity: (
                activity.action_day == day
                and activity.item is not None
                and activity.item.id == asset_id
                and activity.target is not None
                and activity.target.type == "user"
                and str(activity.target.id) == str(self._snipeit_user_id)
                and (after_log_id is None or activity.id > after_log_id)
                and _activity_matches_time(activity, at, exact=exact)
            ),
        )
        return [activity.id for activity in matches]

    async def _matching_activity(
        self,
        *,
        asset_id: int,
        action_type: str,
        matches: Callable[[SnipeItActivity], bool],
    ) -> list[SnipeItActivity]:
        """Page the asset's ``action_type`` activity, newest first, keeping ``matches``.

        Returns nothing when the report is unavailable or unreadable, so callers
        treat it as best-effort.
        """
        found: list[SnipeItActivity] = []
        try:
            for page in range(1, _ACTIVITY_MAX_PAGES + 1):
                response = await self._api_client.list_asset_activity(
                    asset_id, action_type=action_type, page=page, per_page=_PAGE_SIZE
                )
                found.extend(
                    activity
                    for activity in response.rows
                    # Checked here too: some Snipe-IT versions (e.g. 6.3.1)
                    # ignore the report's action_type filter.
                    if activity.action_type == action_type and matches(activity)
                )
                if len(response.rows) < _PAGE_SIZE:
                    break
            else:
                logger.warning(
                    "Stopped searching Snipe-IT activity at the page limit",
                    snipeit_asset_id=asset_id,
                    action_type=action_type,
                )
        except SnipeItAPIError as exc:
            # Transient and auth failures must still retry; a report this API key
            # may not read, or this Snipe-IT version lacks, only skips linking.
            if exc.status_code not in (403, 404):
                raise
            logger.warning(
                "Snipe-IT activity report unavailable; recording without linking",
                snipeit_asset_id=asset_id,
                status_code=exc.status_code,
            )
            return []
        except ValueError:
            # Covers both a body that is not JSON (JSONDecodeError) and one that
            # does not match the report's shape (pydantic's ValidationError).
            logger.warning(
                "Snipe-IT activity report unreadable; recording without linking",
                snipeit_asset_id=asset_id,
            )
            return []
        return found

    async def _claim_activity_log(
        self,
        candidates: list[int],
        *,
        source: str,
        asset_id: int,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        defer_to_posting: bool = False,
    ) -> int | None:
        """Claim the first candidate no other journal holds, or return ``None``.

        The claim is merged into this journal's in-progress ``source`` row while
        a per-asset advisory lock is held, so journals processed at once see each
        other's claims and cannot both link one Snipe-IT entry. A claim left on a
        failed row is stale and ignored. Only this user's journals count: log ids
        are unique within one Snipe-IT instance, and each user has their own.

        With ``defer_to_posting``, a claim waits while another journal is posting
        on the asset: a candidate may be its entry, not yet claimed.

        Raises:
            SnipeItSyncInProgress: ``defer_to_posting`` met another journal's
                in-flight post on this asset.
        """
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                    {"lock_key": f"{source}:{asset_id}"},
                )
                if defer_to_posting and await self._posting_elsewhere(
                    session, source=source, asset_id=asset_id, journal_id=journal_id
                ):
                    raise SnipeItSyncInProgress(
                        f"Another checkout of asset {asset_id} is being posted"
                    )
                result = await session.execute(
                    text("""
                        SELECT sm.reference_data::jsonb ->> 'snipeit_log_id' AS log_id
                        FROM sync_metadata sm
                        JOIN journals j ON j.id::text = sm.internal_uuid
                        WHERE sm.integration_source = :source
                          AND sm.internal_uuid <> :journal_id
                          AND sm.sync_status <> 'failed'
                          AND sm.reference_data LIKE :linked_pattern
                          AND j.user_id = :user_id
                    """),
                    {
                        "source": source,
                        "journal_id": str(journal_id),
                        "linked_pattern": '%"snipeit_log_id"%',
                        "user_id": self._user_id,
                    },
                )
                held = {row.log_id for row in result.fetchall()}
                log_id = next(
                    (
                        candidate
                        for candidate in candidates
                        if str(candidate) not in held
                    ),
                    None,
                )
                if log_id is None:
                    return None
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET reference_data = (
                                COALESCE(reference_data, '{}')::jsonb
                                || CAST(:claim AS jsonb)
                            )::text,
                            updated_at = now()
                        WHERE integration_source = :source
                          AND internal_uuid = :journal_id
                          AND external_id = :external_id
                    """),
                    {
                        "claim": json.dumps({"snipeit_log_id": log_id}),
                        "source": source,
                        "journal_id": str(journal_id),
                        "external_id": external_id,
                    },
                )
        return log_id

    async def _posting_elsewhere(
        self, session: Any, *, source: str, asset_id: int, journal_id: int
    ) -> bool:
        """Whether another of the user's journals is posting on this asset now."""
        result = await session.execute(
            text("""
                SELECT 1
                FROM sync_metadata sm
                JOIN journals j ON j.id::text = sm.internal_uuid
                WHERE sm.integration_source = :source
                  AND sm.external_id LIKE :asset_prefix
                  AND sm.internal_uuid <> :journal_id
                  AND sm.sync_status = 'pending'
                  AND sm.updated_at > now() - make_interval(secs => :in_flight)
                  AND sm.reference_data LIKE :posting_pattern
                  AND (sm.reference_data::jsonb ->> :posting) = 'true'
                  AND j.user_id = :user_id
                LIMIT 1
            """),
            {
                "source": source,
                "asset_prefix": f"{source}:{asset_id}:%",
                "journal_id": str(journal_id),
                "in_flight": IN_FLIGHT_LOCK_SECONDS,
                "posting_pattern": f'%"{_POSTING}"%',
                "posting": _POSTING,
                "user_id": self._user_id,
            },
        )
        return result.fetchone() is not None

    async def _unlock_pending_checkout(
        self,
        journal_id: int,
        session_factory: Any,
        error_message: str,
    ) -> None:
        """Mark a pending checkout sync as failed to release the lock for future retries.

        The row is found by journal, not external id: it may still be keyed to a
        previous attempt's asset.
        """
        try:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'failed',
                                updated_at = now(),
                                error_message = :error_message
                            WHERE integration_source = 'snipeit_checkout'
                              AND internal_uuid = :internal_uuid
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "error_message": error_message,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to unlock pending checkout",
                journal_id=journal_id,
                error=str(exc),
            )

    # -- Outbound Checkin Sync Methods --------------------------------------

    async def push_checkin_create(
        self,
        journal_id: int,
        session_factory: Any,
        note: str | None = None,
        checkin_at: date | None = None,
        usage_dates: AssetUsageDates | None = None,
    ) -> bool:
        """Return (check in) the asset previously checked out for a GEAR_USAGE journal.

        The asset is resolved from the existing ``snipeit_checkout`` sync metadata
        row for ``journal_id`` rather than the journal/gear-usage tables, so this
        still works after the journal (and its cascade-deleted usage data) is gone
        — e.g. when triggered by ``JournalDeleted``. A no-op when no successful
        checkout was recorded. Idempotency is enforced via a ``snipeit_checkin``
        sync metadata row, mirroring :meth:`push_checkout_create`.

        Args:
            journal_id: Internal journal ID whose checkout should be reversed.
            session_factory: Async session factory for DB queries.
            note: Optional note recorded on the Snipe-IT check-in (the usage
                window, when known).
            checkin_at: The local date the asset was returned. Sent as Snipe-IT's
                ``checkin_at`` so the check-in is backdated; ``None`` lets
                Snipe-IT stamp the check-in now (e.g. on journal deletion).
            usage_dates: The usage's own checkout and check-in times. Snipe-IT
                sets the asset's last check-in to now (and a historical checkout
                replaced its last checkout), so after a posted check-in each is
                restored to the later of these and the asset's dates from before
                the checkout. ``None`` leaves the asset's dates as Snipe-IT set
                them (e.g. on journal deletion, when now is right).

        Returns:
            ``True`` only when a check-in was actively performed against Snipe-IT;
            ``False`` for any no-op (no checkout, already checked in) or terminal
            non-retryable outcome (403/404).

        Raises:
            SnipeItSyncInProgress: Another worker holds this journal's check-in.
                The caller's event must be retried rather than acknowledged: a
                checkout-date change arriving now could otherwise never supersede
                the check-in once it lands.
        """
        # 1. Resolve the asset and confirm a successful checkout exists.
        async with session_factory() as session:
            checkout_result = await session.execute(
                text("""
                    SELECT external_id, sync_status, reference_data
                    FROM sync_metadata
                    WHERE integration_source = 'snipeit_checkout'
                      AND internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            checkout_row = checkout_result.fetchone()

        if not checkout_row or checkout_row.sync_status != "success":
            logger.debug(
                "Skipping checkin: no successful checkout recorded for journal",
                journal_id=journal_id,
            )
            return False

        snipeit_asset_id = _checkout_asset_id(checkout_row.external_id)
        if snipeit_asset_id is None:
            logger.warning(
                "Invalid checkout sync metadata external_id; cannot derive asset",
                external_id=checkout_row.external_id,
                journal_id=journal_id,
            )
            return False

        external_id = f"snipeit_checkin:{snipeit_asset_id}:{journal_id}"

        # 2. Acquire a distributed lock by marking the checkin as pending.
        async with session_factory() as session:
            async with session.begin():
                # Key on (integration_source, external_id) — the table's unique
                # key — so the lock and finalize always target exactly this row.
                checkin_meta_result = await session.execute(
                    text("""
                        SELECT sync_status, extract(epoch from (now() - updated_at)) as age_seconds
                        FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkin'
                          AND external_id = :external_id
                        FOR UPDATE SKIP LOCKED
                    """),
                    {"external_id": external_id},
                )
                row = checkin_meta_result.fetchone()
                if row:
                    if row.sync_status == "success":
                        logger.debug(
                            "Skipping checkin: already checked in",
                            journal_id=journal_id,
                        )
                        return False
                    if (
                        row.sync_status == "pending"
                        and row.age_seconds is not None
                        and row.age_seconds < IN_FLIGHT_LOCK_SECONDS
                    ):
                        raise SnipeItSyncInProgress(
                            f"Check-in of journal {journal_id} is in flight"
                        )

                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'pending', updated_at = now()
                            WHERE integration_source = 'snipeit_checkin' AND external_id = :external_id
                        """),
                        {"external_id": external_id},
                    )
                else:
                    insert_result = await session.execute(
                        text("""
                            INSERT INTO sync_metadata
                                (internal_uuid, integration_source, external_id,
                                 last_synced_at, version_hash, sync_status,
                                 error_message, retry_count, created_at, updated_at)
                            VALUES
                                (:internal_uuid, 'snipeit_checkin', :external_id,
                                 now(), 'PENDING', 'pending', NULL, 0, now(), now())
                            ON CONFLICT (integration_source, external_id) DO NOTHING
                            RETURNING id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                        },
                    )
                    if not insert_result.fetchone():
                        raise SnipeItSyncInProgress(
                            f"Check-in of journal {journal_id} is locked by another worker"
                        )

        # 3. Build the checkin payload and POST to Snipe-IT.
        payload: dict[str, Any] = {}
        if note:
            payload["note"] = note
        if checkin_at:
            payload["checkin_at"] = checkin_at.isoformat()

        # A checkout linked to existing Snipe-IT history may already have been
        # returned there too; link that check-in rather than POST another.
        checkout_log_id = self._recorded_log_id(checkout_row.reference_data)
        linked_log_id: int | None = None
        restore_baseline: AssetUsageDates | None = None
        try:
            if checkin_at and checkout_log_id is not None:
                linked_log_id = await self._find_unlinked_activity(
                    asset_id=snipeit_asset_id,
                    action_type="checkin from",
                    day=checkin_at.isoformat(),
                    source="snipeit_checkin",
                    journal_id=journal_id,
                    external_id=external_id,
                    session_factory=session_factory,
                    after_log_id=checkout_log_id,
                )
            if linked_log_id is None:
                if usage_dates is not None:
                    restore_baseline = await self._checkin_restore_baseline(
                        snipeit_asset_id, checkout_row.reference_data
                    )
                await self._api_client.checkin_asset(
                    asset_id=snipeit_asset_id,
                    payload=payload,
                )
        except SnipeItAPIError as exc:
            # 403/404 is non-retryable: the asset is already returned / gone (404)
            # or we are not permitted to return it (403). Record a terminal
            # outcome so the periodic sweep and update reconcile stop re-attempting
            # it (a 'failed' row would be re-selected every sweep).
            if exc.status_code in (403, 404):
                logger.warning(
                    "Snipe-IT checkin failed (not found/forbidden); marking terminal",
                    journal_id=journal_id,
                    snipeit_asset_id=snipeit_asset_id,
                    status_code=exc.status_code,
                )
                await self._finalize_checkin(
                    journal_id,
                    external_id,
                    session_factory,
                    error_message=f"Terminal: API {exc.status_code}",
                    checkin_at=checkin_at,
                )
                return False

            await self._unlock_pending_checkin(
                journal_id, external_id, session_factory, str(exc)[:255]
            )
            raise
        except Exception as exc:
            await self._unlock_pending_checkin(
                journal_id, external_id, session_factory, str(exc)[:255]
            )
            raise

        # 4. Record the checkin as successful.
        await self._finalize_checkin(
            journal_id,
            external_id,
            session_factory,
            checkin_at=checkin_at,
            snipeit_log_id=linked_log_id,
        )

        if linked_log_id is not None:
            logger.info(
                "Linked existing Snipe-IT check-in",
                journal_id=journal_id,
                snipeit_asset_id=snipeit_asset_id,
                snipeit_log_id=linked_log_id,
            )
            return False

        logger.info(
            "Successfully checked in asset to Snipe-IT",
            journal_id=journal_id,
            snipeit_asset_id=snipeit_asset_id,
        )
        if usage_dates is not None and restore_baseline is not None:
            # A checkout linked to existing history left Snipe-IT's own date,
            # unless the worker read the asset first: it posted that checkout
            # itself and linked it only because the response was lost.
            worker_checkout = (
                checkout_log_id is None
                or AssetUsageDates.from_reference(checkout_row.reference_data)
                is not None
            )
            await self._restore_asset_dates(
                snipeit_asset_id,
                restore_baseline.latest(usage_dates).payload(
                    include_checkout=worker_checkout
                ),
                journal_id=journal_id,
            )
        return True

    async def _checkin_restore_baseline(
        self, asset_id: int, checkout_reference: object
    ) -> AssetUsageDates | None:
        """Return the asset dates a check-in's restore must not move backwards.

        These are the dates read before the journal's checkout. A checkout
        recorded without them (before they were kept, or linked to existing
        history) falls back to the asset as it is now: still checked out, so its
        last check-in is the one before this usage. ``None`` when that read
        fails, as restoring against nothing could move a later date back.
        """
        kept = AssetUsageDates.from_reference(checkout_reference)
        if kept is not None:
            return kept
        try:
            asset = await self._api_client.get_asset(asset_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not read Snipe-IT asset dates; they will not be restored",
                snipeit_asset_id=asset_id,
                exc_info=True,
            )
            return None
        return AssetUsageDates.from_asset(asset)

    async def _restore_asset_dates(
        self, asset_id: int, payload: dict[str, str], *, journal_id: int
    ) -> None:
        """PATCH an asset's last checkout/check-in after a posted check-in.

        Best-effort: the check-in is already recorded, and a failure only leaves
        these display dates wrong, whereas raising would retry, and so re-post,
        a check-in Snipe-IT already has.
        """
        if not payload:
            return
        try:
            await self._api_client.update_asset(asset_id, payload)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to restore Snipe-IT asset dates after check-in",
                journal_id=journal_id,
                snipeit_asset_id=asset_id,
                exc_info=True,
            )

    async def _finalize_checkin(
        self,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        error_message: str | None = None,
        checkin_at: date | None = None,
        snipeit_log_id: int | None = None,
    ) -> None:
        """Mark a checkin sync row terminal (``success``) so it is not retried.

        Used both for a confirmed return and for non-retryable 403/404 outcomes
        (which carry an ``error_message`` for diagnostics). A terminal ``success``
        row removes the journal from the periodic sweep's selection.
        """
        reference: dict[str, Any] = {
            "checkin_at": checkin_at.isoformat() if checkin_at else None
        }
        if snipeit_log_id is not None:
            reference["snipeit_log_id"] = snipeit_log_id
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET version_hash = 'CHECKED_IN',
                            last_synced_at = now(),
                            sync_status = 'success',
                            error_message = :error_message,
                            reference_data = :reference_data,
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkin'
                          AND internal_uuid = :internal_uuid
                          AND external_id = :external_id
                    """),
                    {
                        "internal_uuid": str(journal_id),
                        "external_id": external_id,
                        "error_message": error_message,
                        "reference_data": json.dumps(reference),
                    },
                )

    async def _unlock_pending_checkin(
        self,
        journal_id: int,
        external_id: str,
        session_factory: Any,
        error_message: str,
    ) -> None:
        """Mark a pending checkin sync as failed to release the lock for future retries."""
        try:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("""
                            UPDATE sync_metadata
                            SET sync_status = 'failed',
                                updated_at = now(),
                                error_message = :error_message
                            WHERE integration_source = 'snipeit_checkin'
                              AND internal_uuid = :internal_uuid
                              AND external_id = :external_id
                        """),
                        {
                            "internal_uuid": str(journal_id),
                            "external_id": external_id,
                            "error_message": error_message,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to unlock pending checkin",
                journal_id=journal_id,
                error=str(exc),
            )

    async def reconcile_gear_usage(
        self,
        journal_id: int,
        session_factory: Any,
    ) -> None:
        """Reconcile a GEAR_USAGE journal's Snipe-IT state after an update.

        Desired state: the asset is checked out on the journal's local checkout
        date and, once the usage period has ended, checked in on its local
        check-in date. Snipe-IT's activity log cannot be edited, so history is
        only added where it is missing:

        - No successful checkout: create it (which checks the asset straight
          back in when the period is already past).
        - The checkout date changed after the asset was checked in: supersede
          the recorded pair and record a new checkout and check-in.
        - The checkout was linked to another usage's log entry (one at another
          time of that day) and the asset is back: release the linked pair and
          record the journal's own.
        - Otherwise: check the asset in once the period has ended. This is a
          no-op when already checked in, so a changed check-in date alone is not
          re-recorded. If the check-in closes a checkout recorded on an older
          date, the corrected pair is recorded straight after.

        A checkout recorded before its dates were stored, or one whose check-in
        ended in a terminal 403/404 (the asset may still be out), is never
        superseded.
        """
        async with session_factory() as session:
            checkout_result = await session.execute(
                text("""
                    SELECT co.sync_status, co.external_id, co.reference_data,
                           ci.sync_status AS checkin_status,
                           ci.error_message AS checkin_error
                    FROM sync_metadata co
                    LEFT JOIN sync_metadata ci
                        ON ci.integration_source = 'snipeit_checkin'
                        AND ci.internal_uuid = co.internal_uuid
                    WHERE co.integration_source = 'snipeit_checkout'
                      AND co.internal_uuid = :journal_id
                """),
                {"journal_id": str(journal_id)},
            )
            checkout_row = checkout_result.fetchone()

        if not checkout_row or checkout_row.sync_status != "success":
            # No successful checkout yet — create it (handles immediate checkin).
            await self.push_checkout_create(
                journal_id=journal_id,
                session_factory=session_factory,
            )
            return

        data = await self._fetch_journal_and_gear_usage_data(
            journal_id, session_factory
        )
        if not data:
            return

        journal_row, usage_data_row, _ = data
        zone = _snipeit_zone(journal_row)
        checkout_date = (
            usage_data_row.checkout_date or journal_row.event_date_range_start
        )
        checkin_date = usage_data_row.checkin_date or journal_row.event_date_range_end

        recorded_checkout_at = self._recorded_checkout_at(checkout_row.reference_data)
        checkout_at = _format_date_for_snipeit(checkout_date, zone)
        checkout_date_changed = (
            recorded_checkout_at is not None
            and checkout_at is not None
            and recorded_checkout_at != checkout_at
        )
        if (
            checkout_date_changed
            and checkout_row.checkin_status == "success"
            and checkout_row.checkin_error is None
        ):
            if await self._asset_is_free(
                checkout_row.external_id, journal_id=journal_id
            ) and await self._supersede_checkout(
                journal_id=journal_id,
                recorded_reference=checkout_row.reference_data,
                session_factory=session_factory,
                reason="checkout date changed",
            ):
                await self.push_checkout_create(
                    journal_id=journal_id,
                    session_factory=session_factory,
                )
            return

        if (
            not checkout_date_changed
            and checkout_row.checkin_status == "success"
            and checkout_row.checkin_error is None
            and await self._linked_to_another_checkout(
                checkout_row.external_id,
                checkout_row.reference_data,
                at=_snipeit_datetime(checkout_date, zone),
            )
        ):
            if await self._asset_is_free(
                checkout_row.external_id, journal_id=journal_id
            ) and await self._supersede_checkout(
                journal_id=journal_id,
                recorded_reference=checkout_row.reference_data,
                session_factory=session_factory,
                reason="linked log entry belongs to another checkout",
            ):
                await self.push_checkout_create(
                    journal_id=journal_id,
                    session_factory=session_factory,
                )
            return

        if _usage_period_has_ended(checkin_date):
            note = (
                f"Usage period {checkout_at} "
                f"to {_format_date_for_snipeit(checkin_date, zone)}"
            )
            checked_in = await self.push_checkin_create(
                journal_id=journal_id,
                session_factory=session_factory,
                note=note,
                checkin_at=_snipeit_checkin_at(_local_date(checkin_date, zone)),
                usage_dates=AssetUsageDates.from_instants(
                    checkout_date, checkin_date, zone
                ),
            )
            if checked_in and checkout_date_changed:
                # That check-in closed a checkout recorded on the old date; with
                # the asset back, the pass above now records the corrected pair.
                await self.reconcile_gear_usage(journal_id, session_factory)

    async def _asset_is_free(self, external_id: object, *, journal_id: int) -> bool:
        """Whether a checkout row's asset is checked in, so a new pair can be recorded.

        This journal's check-in does not mean the asset is free now: another
        usage may have it out, and Snipe-IT refuses to check out an asset that
        is. The recorded pair is then kept, to be re-recorded by a later update.
        """
        asset_id = _checkout_asset_id(external_id)
        if asset_id is None:
            return False
        try:
            asset = await self._api_client.get_asset(asset_id)
        except SnipeItAPIError as exc:
            if exc.status_code in (403, 404):
                return False
            raise
        if asset.assigned_to is not None:
            logger.info(
                "Keeping recorded Snipe-IT pair while the asset is checked out",
                journal_id=journal_id,
                snipeit_asset_id=asset_id,
            )
            return False
        return True

    async def _supersede_checkout(
        self,
        *,
        journal_id: int,
        recorded_reference: str,
        session_factory: Any,
        reason: str,
    ) -> bool:
        """Release a journal's recorded checkout and check-in so a new pair is made.

        The checkout row is reset to ``failed``, which :meth:`push_checkout_create`
        retries, and the check-in row is removed. The reset only matches while
        the row still holds ``recorded_reference``, so a concurrent update that
        read the same dates matches nothing and returns ``False`` instead of
        recording a second pair.
        """
        async with session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    text("""
                        UPDATE sync_metadata
                        SET sync_status = 'failed',
                            error_message = :error_message,
                            updated_at = now()
                        WHERE integration_source = 'snipeit_checkout'
                          AND internal_uuid = :journal_id
                          AND sync_status = 'success'
                          AND reference_data = :recorded_reference
                        RETURNING id
                    """),
                    {
                        "journal_id": str(journal_id),
                        "recorded_reference": recorded_reference,
                        "error_message": f"Superseded: {reason}",
                    },
                )
                if result.fetchone() is None:
                    logger.debug(
                        "Skipping checkout supersede: already superseded",
                        journal_id=journal_id,
                    )
                    return False
                await session.execute(
                    text("""
                        DELETE FROM sync_metadata
                        WHERE integration_source = 'snipeit_checkin'
                          AND internal_uuid = :journal_id
                    """),
                    {"journal_id": str(journal_id)},
                )

        logger.info(
            "Superseded Snipe-IT checkout",
            journal_id=journal_id,
            reason=reason,
        )
        return True

    async def _linked_to_another_checkout(
        self, external_id: object, reference_data: object, *, at: str | None
    ) -> bool:
        """Whether a linked checkout's log entry is another checkout's, not this one's.

        Only a checkout linked without reading the asset first is checked: one
        the worker read the asset for was posted by it and linked only because
        the response was lost. Such an entry with a time of day other than
        ``at`` is another usage of the asset that day, which a checkout used to
        link before posted entries were kept.
        """
        log_id = self._recorded_log_id(reference_data)
        if log_id is None or AssetUsageDates.from_reference(reference_data) is not None:
            return False
        asset_id = _checkout_asset_id(external_id)
        if asset_id is None:
            return False
        linked = await self._matching_activity(
            asset_id=asset_id,
            action_type="checkout",
            matches=lambda activity: activity.id == log_id,
        )
        return any(not _activity_matches_time(activity, at) for activity in linked)

    @staticmethod
    def _recorded_reference(reference_data: object) -> dict[str, Any]:
        """Decode a sync row's ``reference_data``, or ``{}`` when it holds none."""
        if not isinstance(reference_data, str):
            return {}
        try:
            recorded = json.loads(reference_data)
        except ValueError:
            return {}
        return recorded if isinstance(recorded, dict) else {}

    @classmethod
    def _recorded_checkout_at(cls, reference_data: object) -> str | None:
        """Return the ``checkout_at`` a checkout sync row recorded, if any."""
        value = cls._recorded_reference(reference_data).get("checkout_at")
        return value if isinstance(value, str) else None

    @classmethod
    def _recorded_log_id(cls, reference_data: object) -> int | None:
        """Return the Snipe-IT log id a sync row was linked to, if any."""
        value = cls._recorded_reference(reference_data).get("snipeit_log_id")
        return value if isinstance(value, int) else None


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    """Return the later of two optional datetimes (a missing one loses)."""
    return max((value for value in (first, second) if value is not None), default=None)


@dataclass(frozen=True)
class AssetUsageDates:
    """An asset's last checkout and check-in, as Snipe-IT's naive wall-clock times.

    Snipe-IT sets an asset's ``last_checkin`` to the moment a check-in is posted
    and its ``last_checkout`` to whatever a checkout says, so recording past
    usage leaves both wrong. The dates read before the worker checks an asset
    out are kept on the checkout sync row, and after the check-in each is
    restored to the later of that value and the usage's own date, so importing
    an older trip never makes an asset look less recently used.
    """

    last_checkout: datetime | None = None
    last_checkin: datetime | None = None

    @classmethod
    def from_asset(cls, asset: SnipeItAsset) -> AssetUsageDates:
        """Read the dates of a ``GET /hardware/{id}`` response."""
        return cls(
            last_checkout=_parse_wall_clock(
                asset.last_checkout.datetime if asset.last_checkout else None
            ),
            last_checkin=_parse_wall_clock(
                asset.last_checkin.datetime if asset.last_checkin else None
            ),
        )

    @classmethod
    def from_instants(
        cls,
        checkout: date | datetime | None,
        checkin: date | datetime | None,
        zone: str | None,
    ) -> AssetUsageDates:
        """The usage's own checkout and check-in, read in Snipe-IT's zone."""
        return cls(
            last_checkout=_snipeit_wall_clock(checkout, zone),
            last_checkin=_snipeit_wall_clock(checkin, zone),
        )

    @classmethod
    def from_reference(cls, reference_data: object) -> AssetUsageDates | None:
        """Return the dates a checkout sync row kept, or ``None`` if it kept none."""
        kept = SnipeItSyncService._recorded_reference(reference_data).get(
            _ASSET_DATES_BEFORE
        )
        if not isinstance(kept, dict):
            return None
        return cls(
            last_checkout=_parse_wall_clock(kept.get("last_checkout")),
            last_checkin=_parse_wall_clock(kept.get("last_checkin")),
        )

    def to_reference(self) -> dict[str, str | None]:
        """The dates as kept on a checkout sync row's ``reference_data``."""
        return {
            "last_checkout": _format_wall_clock(self.last_checkout),
            "last_checkin": _format_wall_clock(self.last_checkin),
        }

    def latest(self, other: AssetUsageDates) -> AssetUsageDates:
        """Each date as the later of this one and ``other``'s."""
        return AssetUsageDates(
            last_checkout=_later(self.last_checkout, other.last_checkout),
            last_checkin=_later(self.last_checkin, other.last_checkin),
        )

    def payload(self, *, include_checkout: bool) -> dict[str, str]:
        """The ``PATCH /hardware/{id}`` fields setting the dates that are known."""
        fields = {"last_checkin": self.last_checkin}
        if include_checkout:
            fields["last_checkout"] = self.last_checkout
        return {
            name: value.strftime(_SNIPEIT_DATETIME_FORMAT)
            for name, value in fields.items()
            if value is not None
        }


@dataclass(frozen=True)
class OverdueGearUsage:
    """A checked-out GEAR_USAGE journal whose usage period has ended.

    Dates are the local calendar dates the usage ran over, read in the user's
    configured timezone (see :func:`_snipeit_zone`).
    """

    journal_id: int
    checkout_at: date | None
    checkin_at: date
    usage_dates: AssetUsageDates | None = None

    @property
    def note(self) -> str:
        """The usage window recorded on the Snipe-IT check-in."""
        start = self.checkout_at.isoformat() if self.checkout_at else "unknown"
        return f"Usage period {start} to {self.checkin_at.isoformat()}"

    def snipeit_checkin_at(self, *, now: datetime | None = None) -> date | None:
        """The ``checkin_at`` to send Snipe-IT (``None`` while it may be today there)."""
        return _snipeit_checkin_at(self.checkin_at, now=now)


async def fetch_overdue_gear_usage(
    session_factory: Any, user_id: str
) -> list[OverdueGearUsage]:
    """Return a user's successful checkouts with no check-in whose period has ended.

    Drives the periodic check-in sweep. The resolved check-in instant is compared
    against ``now()``, matching :func:`_usage_period_has_ended`; the returned
    dates are local to the user's configured zone.
    """
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT j.id AS journal_id,
                       COALESCE(u.checkin_date, j.event_date_range_end) AS checkin_date,
                       COALESCE(u.checkout_date, j.event_date_range_start) AS checkout_date,
                       us.timezone AS user_timezone
                FROM sync_metadata co
                JOIN journals j ON j.id = co.internal_uuid::integer
                JOIN journal_gear_usage_data u ON u.journal_id = j.id
                LEFT JOIN user_settings us ON us.user_id = j.user_id
                LEFT JOIN sync_metadata ci
                    ON ci.integration_source = 'snipeit_checkin'
                    AND ci.internal_uuid = co.internal_uuid
                    AND ci.sync_status = 'success'
                WHERE co.integration_source = 'snipeit_checkout'
                  AND co.sync_status = 'success'
                  AND j.user_id = :user_id
                  AND ci.id IS NULL
                  AND COALESCE(u.checkin_date, j.event_date_range_end) < now()
                ORDER BY j.id
            """),
            {"user_id": user_id},
        )
        rows = result.fetchall()

    overdue: list[OverdueGearUsage] = []
    for row in rows:
        zone = _snipeit_zone(row)
        checkin_at = _local_date(row.checkin_date, zone)
        if checkin_at is None:
            continue
        overdue.append(
            OverdueGearUsage(
                journal_id=row.journal_id,
                checkout_at=_local_date(row.checkout_date, zone),
                checkin_at=checkin_at,
                usage_dates=AssetUsageDates.from_instants(
                    row.checkout_date, row.checkin_date, zone
                ),
            )
        )
    return overdue
