"""Unit tests for ImmichSyncService.

Tests people sync logic with mocked database and API dependencies.
Covers name parsing, version hash calculation, sync flow variants
(ExternalReference hit, single match, multi-match, no match), and
birthday sync logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _make_contact_row(
    contact_id: int,
    first_name: str,
    last_name: str | None = None,
    middle_name: str | None = None,
) -> MagicMock:
    """Create a mock contact row (simulates DB row)."""
    row = MagicMock()
    row.id = contact_id
    row.first_name = first_name
    row.last_name = last_name
    row.middle_name = middle_name
    return row


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
    # Default: commit is a no-op
    conn.commit = AsyncMock()
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

        assert hash_a != hash_b  # different birthdate
        assert hash_a != hash_c  # different name
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
# Name parsing (delegated to ContactNameMatcher but called via sync service)
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
# Birthday sync logic
# ---------------------------------------------------------------------------


class TestBirthdaySyncLogic:
    """Tests for birthday creation/skip logic."""

    def test_parse_birth_date_full(self, service: ImmichSyncService) -> None:
        """Parse ISO date string into year, month, day."""
        result = service.parse_birth_date("1990-05-15")
        assert result is not None
        year, month, day = result
        assert year == 1990
        assert month == 5
        assert day == 15

    def test_parse_birth_date_none(self, service: ImmichSyncService) -> None:
        """None birth_date returns None."""
        result = service.parse_birth_date(None)
        assert result is None

    def test_parse_birth_date_invalid(self, service: ImmichSyncService) -> None:
        """Invalid date string returns None."""
        result = service.parse_birth_date("not-a-date")
        assert result is None


# ---------------------------------------------------------------------------
# Sync people flow
# ---------------------------------------------------------------------------


class TestSyncPeopleFlow:
    """Integration-level unit tests for the sync_people method with mocks."""

    @pytest.mark.asyncio
    async def test_skips_unnamed_people(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """People without names are skipped."""
        unnamed = _make_person("p1", "")  # No name
        mock_api_client.get_all_people.return_value = _make_people_response([unnamed])

        result = await service.sync_people()

        assert result.skipped == 1
        assert result.created == 0
        assert result.linked == 0

    @pytest.mark.asyncio
    async def test_skips_hidden_people(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Hidden people are skipped."""
        hidden = _make_person("p1", "John Smith", is_hidden=True)
        mock_api_client.get_all_people.return_value = _make_people_response([hidden])

        result = await service.sync_people()

        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_existing_external_reference_skips_matching(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Person with existing ExternalReference uses existing link."""
        person = _make_person("p1", "John Smith")
        mock_api_client.get_all_people.return_value = _make_people_response([person])

        # Simulate existing ExternalReference
        ext_ref_row = MagicMock()
        ext_ref_row.id = 1
        ext_ref_row.internal_entity_id = 42
        ext_ref_mock = MagicMock()
        ext_ref_mock.fetchone.return_value = ext_ref_row

        # Simulate existing sync_metadata (version hash unchanged)
        sync_meta_row = MagicMock()
        sync_meta_row.version_hash = service.calculate_version_hash(person)
        sync_meta_mock = MagicMock()
        sync_meta_mock.fetchone.return_value = sync_meta_row

        mock_connection.execute = AsyncMock(side_effect=[ext_ref_mock, sync_meta_mock])

        result = await service.sync_people()

        assert result.unchanged == 1
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_single_contact_match_auto_links(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Person matching a single contact is auto-linked."""
        person = _make_person("p1", "Jane Doe", "1990-03-20")
        mock_api_client.get_all_people.return_value = _make_people_response([person])

        # No existing ExternalReference
        no_ref_mock = MagicMock()
        no_ref_mock.fetchone.return_value = None

        # Contact search returns single match
        contact_row = _make_contact_row(10, "Jane", "Doe")
        contacts_mock = MagicMock()
        contacts_mock.fetchall.return_value = [contact_row]

        # No existing birthday
        no_birthday_mock = MagicMock()
        no_birthday_mock.fetchone.return_value = None

        # Insert results (ExternalReference, SyncMetadata, ImportantDate)
        insert_mock = MagicMock()
        insert_row = MagicMock()
        insert_row.id = 1
        insert_row.created_at = datetime.now(UTC)
        insert_row.updated_at = datetime.now(UTC)
        insert_mock.fetchone.return_value = insert_row

        mock_connection.execute = AsyncMock(
            side_effect=[
                no_ref_mock,  # ExternalReference lookup
                contacts_mock,  # Contact search
                insert_mock,  # ExternalReference create
                insert_mock,  # SyncMetadata upsert
                no_birthday_mock,  # Birthday check
                insert_mock,  # ImportantDate insert
            ]
        )

        result = await service.sync_people()

        assert result.linked == 1
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_multiple_contact_matches_create_conflict(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Person matching multiple contacts creates a conflict."""
        person = _make_person("p1", "John Smith")
        mock_api_client.get_all_people.return_value = _make_people_response([person])

        # No existing ExternalReference
        no_ref_mock = MagicMock()
        no_ref_mock.fetchone.return_value = None

        # Contact search returns multiple matches
        contacts_mock = MagicMock()
        contacts_mock.fetchall.return_value = [
            _make_contact_row(1, "John", "Smith"),
            _make_contact_row(2, "John", "Smith", middle_name="Andrew"),
        ]

        # Conflict insert
        conflict_mock = MagicMock()
        conflict_row = MagicMock()
        conflict_row.id = 1
        conflict_mock.fetchone.return_value = conflict_row

        mock_connection.execute = AsyncMock(
            side_effect=[
                no_ref_mock,  # ExternalReference lookup
                contacts_mock,  # Contact search
                conflict_mock,  # Conflict insert
            ]
        )

        result = await service.sync_people()

        assert result.conflicts == 1

    @pytest.mark.asyncio
    async def test_no_match_creates_new_contact(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """Person with no contact match creates a new contact."""
        person = _make_person("p1", "Bob Jones", "1985-12-25")
        mock_api_client.get_all_people.return_value = _make_people_response([person])

        # No existing ExternalReference
        no_ref_mock = MagicMock()
        no_ref_mock.fetchone.return_value = None

        # Contact search returns no matches
        no_contacts_mock = MagicMock()
        no_contacts_mock.fetchall.return_value = []

        # Contact insert
        contact_insert_mock = MagicMock()
        contact_row = MagicMock()
        contact_row.id = 100
        contact_row.created_at = datetime.now(UTC)
        contact_row.updated_at = datetime.now(UTC)
        contact_insert_mock.fetchone.return_value = contact_row

        # Other inserts (ExternalReference, SyncMetadata, ImportantDate)
        insert_mock = MagicMock()
        insert_row = MagicMock()
        insert_row.id = 1
        insert_row.created_at = datetime.now(UTC)
        insert_row.updated_at = datetime.now(UTC)
        insert_mock.fetchone.return_value = insert_row

        mock_connection.execute = AsyncMock(
            side_effect=[
                no_ref_mock,  # ExternalReference lookup
                no_contacts_mock,  # Contact search
                contact_insert_mock,  # Contact insert
                insert_mock,  # ExternalReference create
                insert_mock,  # SyncMetadata upsert
                insert_mock,  # ImportantDate insert
            ]
        )

        result = await service.sync_people()

        assert result.created == 1
