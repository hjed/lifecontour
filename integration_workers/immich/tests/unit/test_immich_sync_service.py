"""Unit tests for ImmichSyncService.

Tests people sync logic with mocked database and API dependencies.
Covers name parsing, version hash calculation, sync flow variants
(ExternalReference hit, single match, multi-match, no match),
birthday inclusion in outbox data, and photo_url inclusion.

The refactored service emits outbox events for contact mutations
rather than performing direct SQL writes.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import Contact
from sqlalchemy.sql.dml import Insert

from immich_models import ImmichPeopleResponse, ImmichPerson
from immich_sync_service import ImmichSyncService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_person(
    person_id: str,
    name: str,
    birth_date: str | None = None,
    is_hidden: bool = False,
) -> ImmichPerson:
    """Create an ImmichPerson test fixture."""
    return ImmichPerson(
        id=person_id,
        name=name,
        birth_date=birth_date,
        is_hidden=is_hidden,
    )


def _make_people_response(
    people: list[ImmichPerson],
    has_next_page: bool = False,
) -> ImmichPeopleResponse:
    """Wrap people into a paginated response."""
    return ImmichPeopleResponse(
        people=people,
        total=len(people),
        hidden=0,
        has_next_page=has_next_page,
    )


def _make_contact(
    contact_id: int,
    first_name: str,
    last_name: str | None = None,
    middle_name: str | None = None,
) -> Contact:
    """Create a Contact entity, owned by the syncing user, for name matching tests."""
    return Contact(
        id=contact_id,
        first_name=first_name,
        user_id="user-1",
        last_name=last_name,
        middle_name=middle_name,
    )


def _make_fetchone_result(**kwargs: object) -> MagicMock:
    """Create a mock execute result where fetchone() returns a row with attrs."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def _make_fetchone_none() -> MagicMock:
    """Create a mock execute result where fetchone() returns None."""
    result = MagicMock()
    result.fetchone.return_value = None
    return result


def _make_fetchall_result(rows: list[MagicMock]) -> MagicMock:
    """Create a mock execute result where fetchall() returns rows."""
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def _make_contact_row(
    contact_id: int,
    first_name: str,
    last_name: str | None = None,
    middle_name: str | None = None,
) -> MagicMock:
    """Create a mock DB row with contact fields."""
    row = MagicMock()
    row.id = contact_id
    row.first_name = first_name
    row.last_name = last_name
    row.middle_name = middle_name
    return row


def _extract_outbox_events(mock_connection: AsyncMock) -> list[dict[str, Any]]:
    """Extract outbox event payloads from mock connection execute calls.

    Outbox events are emitted as ``insert(OutboxEvent).values(...)`` Core
    statements, so inspect each execute call for an Insert targeting the
    ``outbox_events`` table and read its bound values.
    """
    events = []
    for call in mock_connection.execute.call_args_list:
        args = call[0]
        if not args:
            continue
        stmt = args[0]
        if isinstance(stmt, Insert) and stmt.table.name == "outbox_events":
            params = stmt.compile().params
            event_data = params.get("event_data")
            if isinstance(event_data, str):
                event_data = json.loads(event_data)
            events.append(
                {
                    "event_type": params.get("event_type"),
                    "event_data": event_data,
                }
            )
    return events


def _extract_sync_metadata_upserts(
    mock_connection: AsyncMock,
) -> list[dict[str, Any]]:
    """Extract bound params from ``sync_metadata`` upsert statements.

    ``_upsert_sync_metadata`` issues a raw ``text()`` ``INSERT INTO sync_metadata``
    with a bound-param dict as the second execute argument, so match on the SQL
    text and return each call's params for assertion.
    """
    upserts = []
    for call in mock_connection.execute.call_args_list:
        args = call[0]
        if len(args) < 2:
            continue
        stmt, params = args[0], args[1]
        if "INSERT INTO sync_metadata" in str(stmt) and isinstance(params, dict):
            upserts.append(params)
    return upserts


# ---------------------------------------------------------------------------
# Service fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_api_client() -> AsyncMock:
    """Mock ImmichApiClient."""
    return AsyncMock()


@pytest.fixture()
def mock_connection() -> AsyncMock:
    """Mock async database connection."""
    conn = AsyncMock()
    conn.commit = AsyncMock()

    # ``begin_nested()`` returns an async context manager (a SAVEPOINT). Model
    # it as a sync call returning an async CM so ``async with`` works in tests.
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    conn.begin_nested = MagicMock(return_value=nested_cm)

    return conn


@pytest.fixture()
def service(
    mock_api_client: AsyncMock,
    mock_connection: AsyncMock,
) -> ImmichSyncService:
    """Create an ImmichSyncService with mocked dependencies."""
    return ImmichSyncService(
        api_client=mock_api_client,
        connection=mock_connection,
        user_id="user-1",
        integration_source="immich",
    )


# ---------------------------------------------------------------------------
# Version hash calculation
# ---------------------------------------------------------------------------


class TestVersionHash:
    """Tests for version hash computation."""

    def test_hash_includes_name_and_birthdate(self, service: ImmichSyncService) -> None:
        """Version hash changes when name or birthdate changes."""
        person_a = _make_person("p1", "John Smith", "1990-05-15")
        person_b = _make_person("p1", "John Smith", "1991-05-15")
        person_c = _make_person("p1", "Jane Smith", "1990-05-15")

        hash_a = service.calculate_version_hash(person_a)
        hash_b = service.calculate_version_hash(person_b)
        hash_c = service.calculate_version_hash(person_c)

        assert hash_a != hash_b
        assert hash_a != hash_c
        assert hash_b != hash_c

    def test_hash_deterministic(self, service: ImmichSyncService) -> None:
        """Same inputs produce the same hash."""
        person = _make_person("p1", "John Smith", "1990-05-15")
        assert service.calculate_version_hash(person) == service.calculate_version_hash(
            person
        )

    def test_hash_without_birthdate(self, service: ImmichSyncService) -> None:
        """Hash works when birthDate is None."""
        person = _make_person("p1", "John Smith")
        h = service.calculate_version_hash(person)
        assert isinstance(h, str)
        assert len(h) > 0


# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------


class TestNameParsing:
    """Tests for name parsing within the sync flow."""

    def test_two_part_name(self, service: ImmichSyncService) -> None:
        first, last = service.parse_person_name("John Smith")
        assert first == "John"
        assert last == "Smith"

    def test_single_name(self, service: ImmichSyncService) -> None:
        first, last = service.parse_person_name("Madonna")
        assert first == "Madonna"
        assert last is None

    def test_three_part_name(self, service: ImmichSyncService) -> None:
        first, last = service.parse_person_name("John Michael Smith")
        assert first == "John Michael"
        assert last == "Smith"


# ---------------------------------------------------------------------------
# Birthday parsing
# ---------------------------------------------------------------------------


class TestBirthdaySyncLogic:
    """Tests for birthday creation/skip logic."""

    def test_parse_birth_date_full(self, service: ImmichSyncService) -> None:
        result = service.parse_birth_date("1990-05-15")
        assert result is not None
        year, month, day = result
        assert year == 1990
        assert month == 5
        assert day == 15

    def test_parse_birth_date_none(self, service: ImmichSyncService) -> None:
        result = service.parse_birth_date(None)
        assert result is None

    def test_parse_birth_date_invalid(self, service: ImmichSyncService) -> None:
        result = service.parse_birth_date("not-a-date")
        assert result is None


# ---------------------------------------------------------------------------
# Sync people flow
# ---------------------------------------------------------------------------


class TestSyncPeopleFlow:
    """Integration-level unit tests for the sync_people method with mocks.

    The refactored service emits outbox events instead of direct SQL
    for contact creation/update.
    """

    @pytest.mark.asyncio
    async def test_skips_unnamed_people(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """People without names are skipped."""
        unnamed = _make_person("p1", "")

        # No DB calls expected for unnamed people
        mock_connection.execute = AsyncMock(return_value=_make_fetchone_none())

        result = await service.sync_people_batch([unnamed.model_dump()])

        assert result.skipped == 1
        assert result.created == 0
        assert result.linked == 0

    @pytest.mark.asyncio
    async def test_skips_hidden_people(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Hidden people are skipped."""
        hidden = _make_person("p1", "John Smith", is_hidden=True)

        mock_connection.execute = AsyncMock(return_value=_make_fetchone_none())

        result = await service.sync_people_batch([hidden.model_dump()])

        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_existing_external_reference_unchanged(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Person with existing ExternalReference and unchanged hash is skipped."""
        person = _make_person("p1", "John Smith")
        version_hash = service.calculate_version_hash(person)

        # Call sequence for "already linked, unchanged":
        # 1. _find_external_reference -> found
        # 2. _find_sync_metadata -> same hash
        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_result(id=1, internal_entity_id=42),  # ext ref
                _make_fetchone_result(version_hash=version_hash),  # sync meta
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.unchanged == 1
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_existing_reference_version_changed_emits_update(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Person with existing ref but changed hash emits contact.updated."""
        person = _make_person("p1", "John Smith")

        # Call sequence for "already linked, version changed":
        # 1. _find_external_reference -> found (contact_id=42)
        # 2. _find_sync_metadata -> stale hash
        # 3. _emit_outbox_event -> INSERT into outbox_events
        # 4. _upsert_sync_metadata -> upsert
        generic_result = MagicMock()

        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_result(id=1, internal_entity_id=42),  # ext ref
                _make_fetchone_result(version_hash="old-stale-hash"),  # sync meta
                generic_result,  # outbox event insert
                generic_result,  # sync metadata upsert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.updated == 1

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_type"] == "contact.updated"
        assert (
            events[0]["event_data"]["contact_data"]["photo_url"]
            == "/api/contacts/42/avatar"
        )
        # The event and its contact both name the service's user as owner
        assert events[0]["event_data"]["user_id"] == "user-1"
        assert events[0]["event_data"]["contact_data"]["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_single_contact_match_auto_links(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Person matching a single contact is auto-linked via outbox event."""
        person = _make_person("p1", "Jane Doe", "1990-03-20")

        # Pre-populate contacts cache to avoid the contacts fetch call
        service._contacts_cache = [_make_contact(10, "Jane", "Doe")]

        generic_result = MagicMock()

        # Call sequence for "auto-link":
        # 1. _find_external_reference -> not found (reads sync_metadata)
        # 2. _upsert_sync_metadata -> upsert (the canonical link)
        # 3. _emit_outbox_event -> INSERT into outbox_events
        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # link not found
                generic_result,  # sync metadata upsert
                generic_result,  # outbox event insert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.linked == 1
        assert result.created == 0

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_type"] == "contact.updated"
        # The event and its contact both name the service's user as owner
        assert events[0]["event_data"]["user_id"] == "user-1"
        assert events[0]["event_data"]["contact_data"]["user_id"] == "user-1"

        contact_data = events[0]["event_data"]["contact_data"]
        assert contact_data["photo_url"] == "/api/contacts/10/avatar"
        assert contact_data["first_name"] == "Jane"
        assert contact_data["last_name"] == "Doe"

        # Verify birthday is included
        assert contact_data["important_dates"] is not None
        assert len(contact_data["important_dates"]) == 1
        assert contact_data["important_dates"][0]["date_type"] == "birthday"
        assert contact_data["important_dates"][0]["year"] == 1990

    @pytest.mark.asyncio
    async def test_auto_link_writes_sync_metadata_with_entity_types(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Auto-linking writes the canonical sync_metadata link immediately.

        The name-match auto-link path writes the ``sync_metadata`` link in the
        same unit of work (rather than relying on the consumer's later
        ``contact.updated``), carrying the contact/person entity types so the
        canonical link store stays current. It no longer writes
        ``external_references``.
        """
        person = _make_person("p1", "Jane Doe", "1990-03-20")
        service._contacts_cache = [_make_contact(10, "Jane", "Doe")]

        generic_result = MagicMock()
        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # _find_external_reference -> not found
                generic_result,  # _upsert_sync_metadata -> INSERT/upsert
                generic_result,  # _emit_outbox_event -> INSERT outbox_events
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.linked == 1

        upserts = _extract_sync_metadata_upserts(mock_connection)
        assert len(upserts) == 1, "auto-link must write exactly one sync_metadata row"
        params = upserts[0]
        assert params["internal_id"] == 10
        assert params["external_id"] == "p1"
        assert params["integration_source"] == "immich"
        assert params["internal_entity_type"] == "contact"
        assert params["external_entity_type"] == "person"

    @pytest.mark.asyncio
    async def test_multiple_contact_matches_create_conflict(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Person matching multiple contacts creates a conflict."""
        person = _make_person("p1", "John Smith")

        # Pre-populate contacts cache with multiple matches
        service._contacts_cache = [
            _make_contact(1, "John", "Smith"),
            _make_contact(2, "John", "Smith"),
        ]

        # Call sequence for "conflict":
        # 1. _find_external_reference -> not found
        # 2. _create_pending_entity_mapping -> INSERT
        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # ext ref not found
                _make_fetchone_result(id=1),  # pending mapping
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.conflicts == 1

        # No outbox event for conflicts
        events = _extract_outbox_events(mock_connection)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_no_match_creates_new_contact_via_outbox(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Person with no contact match emits a contact.created outbox event."""
        person = _make_person("p1", "Bob Jones", "1985-12-25")

        # Pre-populate empty contacts cache
        service._contacts_cache = []

        generic_result = MagicMock()

        # Call sequence for "create":
        # 1. _find_external_reference -> not found
        # 2. _emit_outbox_event -> INSERT into outbox_events
        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # ext ref not found
                generic_result,  # outbox event insert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])

        assert result.created == 1

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_type"] == "contact.created"
        # The event and its contact both name the service's user as owner
        assert events[0]["event_data"]["user_id"] == "user-1"
        assert events[0]["event_data"]["contact_data"]["user_id"] == "user-1"

        contact_data = events[0]["event_data"]["contact_data"]
        assert contact_data["first_name"] == "Bob"
        assert contact_data["last_name"] == "Jones"
        assert contact_data["photo_url"] is None  # No contact_id yet

        # Verify birthday is included
        assert contact_data["important_dates"] is not None
        assert len(contact_data["important_dates"]) == 1
        assert contact_data["important_dates"][0]["date_type"] == "birthday"
        assert contact_data["important_dates"][0]["year"] == 1985

    @pytest.mark.asyncio
    async def test_failed_person_does_not_abort_remaining_batch(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """A DB error on one person is isolated; later people still process.

        Each person runs inside its own SAVEPOINT (``begin_nested``), so a
        single failure rolls back only that person rather than aborting the
        shared batch transaction and cascading InFailedSQLTransactionError
        onto every subsequent person.
        """
        failing = _make_person("p1", "Andrew Whitham")
        succeeding = _make_person("p2", "Bob Jones", "1985-12-25")

        service._contacts_cache = []

        generic_result = MagicMock()

        # Person 1: first DB call raises (simulating a SQL failure).
        # Person 2: clean "create" flow (find -> none, outbox insert).
        mock_connection.execute = AsyncMock(
            side_effect=[
                RuntimeError("boom"),  # person 1 _find_external_reference
                _make_fetchone_none(),  # person 2 ext ref not found
                generic_result,  # person 2 outbox event insert
            ]
        )

        result = await service.sync_people_batch(
            [failing.model_dump(), succeeding.model_dump()]
        )

        # The failure is recorded but the batch continues.
        assert result.errors == 1
        assert result.created == 1
        assert any("p1" in detail for detail in result.error_details)

        # Each person was wrapped in its own savepoint.
        assert mock_connection.begin_nested.call_count == 2

        # The surviving person still emitted its outbox event.
        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_type"] == "contact.created"
        assert events[0]["event_data"]["contact_data"]["first_name"] == "Bob"


# ---------------------------------------------------------------------------
# Photo URL and contact data in outbox events
# ---------------------------------------------------------------------------


class TestPhotoUrlSync:
    """Tests for photo_url inclusion in outbox event contact data."""

    @pytest.mark.asyncio
    async def test_photo_url_none_on_create(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """New contacts have photo_url=None (set later by processor)."""
        person = _make_person("p1", "Bob Jones")
        service._contacts_cache = []

        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # ext ref not found
                MagicMock(),  # outbox event insert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])
        assert result.created == 1

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_data"]["contact_data"]["photo_url"] is None

    @pytest.mark.asyncio
    async def test_photo_url_included_on_link(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Auto-linked contacts include photo_url in outbox event data."""
        person = _make_person("p1", "Jane Doe")
        service._contacts_cache = [_make_contact(10, "Jane", "Doe")]

        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_none(),  # ext ref not found
                MagicMock(),  # create ext ref
                MagicMock(),  # outbox event insert
                MagicMock(),  # sync metadata upsert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])
        assert result.linked == 1

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert (
            events[0]["event_data"]["contact_data"]["photo_url"]
            == "/api/contacts/10/avatar"
        )

    @pytest.mark.asyncio
    async def test_photo_url_included_on_update(
        self,
        service: ImmichSyncService,
        mock_connection: AsyncMock,
    ) -> None:
        """Updated contacts include photo_url in outbox event data."""
        person = _make_person("p1", "John Smith Updated")

        mock_connection.execute = AsyncMock(
            side_effect=[
                _make_fetchone_result(id=1, internal_entity_id=42),  # ext ref
                _make_fetchone_result(version_hash="old-stale-hash"),  # sync meta
                MagicMock(),  # outbox event insert
                MagicMock(),  # sync metadata upsert
            ]
        )

        result = await service.sync_people_batch([person.model_dump()])
        assert result.updated == 1

        events = _extract_outbox_events(mock_connection)
        assert len(events) == 1
        assert events[0]["event_type"] == "contact.updated"
        assert (
            events[0]["event_data"]["contact_data"]["photo_url"]
            == "/api/contacts/42/avatar"
        )


# ---------------------------------------------------------------------------
# Contact data construction
# ---------------------------------------------------------------------------


class TestBuildContactData:
    """Tests for _build_contact_data helper."""

    def test_build_contact_data_with_birthday(self, service: ImmichSyncService) -> None:
        """Contact data includes birthday when present."""
        person = _make_person("p1", "Jane Doe", "1990-03-20")
        data = service._build_contact_data(person, contact_id=10)

        assert data["first_name"] == "Jane"
        assert data["last_name"] == "Doe"
        assert data["photo_url"] == "/api/contacts/10/avatar"
        assert data["important_dates"] is not None
        assert len(data["important_dates"]) == 1
        assert data["important_dates"][0]["date_type"] == "birthday"
        assert data["important_dates"][0]["year"] == 1990
        assert data["important_dates"][0]["month"] == 3
        assert data["important_dates"][0]["day"] == 20

    def test_build_contact_data_without_birthday(
        self, service: ImmichSyncService
    ) -> None:
        """Contact data has no important_dates when birthday is absent."""
        person = _make_person("p1", "Jane Doe")
        data = service._build_contact_data(person, contact_id=10)

        assert data["first_name"] == "Jane"
        assert data["last_name"] == "Doe"
        assert data["photo_url"] == "/api/contacts/10/avatar"
        assert data["important_dates"] is None

    def test_build_contact_data_no_contact_id(self, service: ImmichSyncService) -> None:
        """Contact data has photo_url=None when contact_id is not known."""
        person = _make_person("p1", "Jane Doe")
        data = service._build_contact_data(person, contact_id=None)

        assert data["photo_url"] is None
        assert data["first_name"] == "Jane"


class TestFetchUserContacts:
    """Name-match candidates are read for the service's user only."""

    @pytest.mark.asyncio
    async def test_reads_only_the_owners_contacts(
        self, service: ImmichSyncService, mock_connection: AsyncMock
    ) -> None:
        """The contacts query is filtered to the syncing user."""
        mock_connection.execute.return_value = _make_fetchall_result([])

        await service._fetch_user_contacts()

        statement, params = mock_connection.execute.await_args.args
        assert "WHERE user_id = :user_id" in str(statement)
        assert params == {"user_id": "user-1"}
