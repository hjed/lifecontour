"""Unit tests for IntegrationLinkRepository (reads of the canonical link store).

These mirror ``test_external_reference_repository.py``: a mocked async
connection lets us assert each method targets ``sync_metadata`` with the right
bound parameters and maps rows correctly, without a real database.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock database connection."""
    return AsyncMock()


@pytest.fixture
def repository(mock_connection: AsyncMock) -> IntegrationLinkRepository:
    """Create a repository with a mock connection."""
    return IntegrationLinkRepository(mock_connection)


def _link_row(**overrides: object) -> MagicMock:
    """Build a sync_metadata-shaped row with sensible defaults."""
    row = MagicMock()
    row.internal_id = 42
    row.internal_uuid = None
    row.integration_source = "google"
    row.external_id = "people/c123"
    row.internal_entity_type = "contact"
    row.external_entity_type = "person"
    row.reference_data = None
    row.version_hash = "vh-1"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _result_with(row: object) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = row
    return result


class TestFindLinkByExternal:
    """Resolve a link by ``(integration_source, external_id)``."""

    @pytest.mark.asyncio
    async def test_returns_mapped_link(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock(
            return_value=_result_with(_link_row(reference_data='{"k": 1}'))
        )

        link = await repository.find_link_by_external(
            "google", "people/c123", user_id="owner-1"
        )

        assert link is not None
        assert link["internal_id"] == 42
        assert link["internal_entity_type"] == "contact"
        assert link["external_entity_type"] == "person"
        assert link["reference_data"] == '{"k": 1}'
        assert link["version_hash"] == "vh-1"
        query, params = mock_connection.execute.call_args[0]
        assert "sync_metadata" in str(query)
        assert params == {
            "user_id": "owner-1",
            "integration_source": "google",
            "external_id": "people/c123",
        }

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock(return_value=_result_with(None))

        assert (
            await repository.find_link_by_external(
                "google", "missing", user_id="owner-1"
            )
            is None
        )


class TestFindExternalByInternal:
    """Resolve the external link for an internal entity."""

    @pytest.mark.asyncio
    async def test_returns_link_filtered_by_entity_type(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock(
            return_value=_result_with(
                _link_row(external_id="person-uuid-1", external_entity_type="person")
            )
        )

        link = await repository.find_external_by_internal(
            internal_entity_type="contact",
            internal_id=42,
            integration_source="immich",
            external_entity_type="person",
        )

        assert link is not None
        assert link["external_id"] == "person-uuid-1"
        assert link["external_entity_type"] == "person"
        _, params = mock_connection.execute.call_args[0]
        assert params["internal_id"] == 42
        assert params["integration_source"] == "immich"
        assert params["internal_entity_type"] == "contact"
        assert params["external_entity_type"] == "person"

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock(return_value=_result_with(None))

        assert (
            await repository.find_external_by_internal(
                internal_entity_type="contact",
                internal_id=1,
                integration_source="immich",
            )
            is None
        )


class TestGetImmichPersonId:
    """Resolve a contact's linked Immich person id from sync_metadata."""

    @pytest.mark.asyncio
    async def test_returns_external_id(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        row = MagicMock()
        row.external_id = "person-uuid-9"
        mock_connection.execute = AsyncMock(return_value=_result_with(row))

        person_id = await repository.get_immich_person_id(99, user_id="owner-1")

        assert person_id == "person-uuid-9"
        query, params = mock_connection.execute.call_args[0]
        assert "sync_metadata" in str(query)
        assert "user_id = :user_id" in str(query)
        assert params == {"contact_id": 99, "user_id": "owner-1"}

    @pytest.mark.asyncio
    async def test_returns_none_when_unlinked(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock(return_value=_result_with(None))

        assert await repository.get_immich_person_id(99, user_id="owner-1") is None


def _person_row(person_id: str, contact_id: int) -> MagicMock:
    row = MagicMock()
    row.external_id = person_id
    row.internal_id = contact_id
    return row


class TestGetContactIdsByImmichPersonIds:
    """Reverse lookup: Immich person ids → local contact ids (from sync_metadata)."""

    @pytest.mark.asyncio
    async def test_maps_resolved_people_and_omits_unknown(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        result = MagicMock()
        result.fetchall.return_value = [
            _person_row("p1", 11),
            _person_row("p2", 22),
        ]
        mock_connection.execute = AsyncMock(return_value=result)

        mapping = await repository.get_contact_ids_by_immich_person_ids(
            ["p1", "p2", "p_unknown"], user_id="owner-1"
        )

        assert mapping == {"p1": 11, "p2": 22}
        _, params = mock_connection.execute.call_args[0]
        assert params == {
            "user_id": "owner-1",
            "person_ids": ["p1", "p2", "p_unknown"],
        }

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits_without_query(
        self,
        repository: IntegrationLinkRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock()

        mapping = await repository.get_contact_ids_by_immich_person_ids(
            [], user_id="owner-1"
        )

        assert mapping == {}
        mock_connection.execute.assert_not_called()
