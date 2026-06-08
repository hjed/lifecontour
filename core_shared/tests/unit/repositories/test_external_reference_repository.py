"""Unit tests for ExternalReferenceRepository."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.repositories.external_reference_repository import (
    ExternalReferenceRepository,
)


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock database connection."""
    return AsyncMock()


@pytest.fixture
def repository(mock_connection: AsyncMock) -> ExternalReferenceRepository:
    """Create a repository with a mock connection."""
    return ExternalReferenceRepository(mock_connection)


def _row(person_id: str, contact_id: int) -> MagicMock:
    row = MagicMock()
    row.external_entity_id = person_id
    row.internal_entity_id = contact_id
    return row


class TestGetContactIdsByImmichPersonIds:
    """Reverse lookup: Immich person ids → local contact ids."""

    @pytest.mark.asyncio
    async def test_maps_resolved_people_and_omits_unknown(
        self,
        repository: ExternalReferenceRepository,
        mock_connection: AsyncMock,
    ) -> None:
        result = MagicMock()
        # Only p1 and p2 are linked; p_unknown has no row → omitted.
        result.fetchall.return_value = [_row("p1", 11), _row("p2", 22)]
        mock_connection.execute = AsyncMock(return_value=result)

        mapping = await repository.get_contact_ids_by_immich_person_ids(
            ["p1", "p2", "p_unknown"]
        )

        assert mapping == {"p1": 11, "p2": 22}
        mock_connection.execute.assert_called_once()
        # The person ids are passed as a bound parameter (no SQL interpolation).
        _, params = mock_connection.execute.call_args[0]
        assert params["person_ids"] == ["p1", "p2", "p_unknown"]

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits_without_query(
        self,
        repository: ExternalReferenceRepository,
        mock_connection: AsyncMock,
    ) -> None:
        mock_connection.execute = AsyncMock()

        mapping = await repository.get_contact_ids_by_immich_person_ids([])

        assert mapping == {}
        mock_connection.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_map(
        self,
        repository: ExternalReferenceRepository,
        mock_connection: AsyncMock,
    ) -> None:
        result = MagicMock()
        result.fetchall.return_value = []
        mock_connection.execute = AsyncMock(return_value=result)

        mapping = await repository.get_contact_ids_by_immich_person_ids(["p9"])

        assert mapping == {}
