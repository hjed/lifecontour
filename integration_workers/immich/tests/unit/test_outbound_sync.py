"""Unit tests for outbound contact sync (ImmichSyncService.sync_contact_outbound).

Validates field mapping, birthday precision filtering, source-of-truth
enforcement, and sync metadata updates when pushing local contact changes
to Immich via PUT /people/{id}.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from immich_models import ImmichPerson
from immich_sync_service import ImmichSyncService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_person(
    person_id: str = "person-uuid-1",
    name: str = "John Smith",
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


def _make_link_dict(
    external_id: str = "person-uuid-1",
    internal_id: int = 42,
) -> dict[str, object]:
    """Create a canonical link dict as returned by IntegrationLinkRepository."""
    return {
        "internal_id": internal_id,
        "internal_uuid": None,
        "integration_source": "immich",
        "external_id": external_id,
        "internal_entity_type": "contact",
        "external_entity_type": "person",
        "reference_data": None,
        "version_hash": None,
    }


def _make_contact_data(
    first_name: str = "John",
    last_name: str | None = "Smith",
    middle_name: str | None = None,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
) -> dict[str, object]:
    """Create a mock contact data dictionary as returned by find_contact_with_birthday."""
    return {
        "first_name": first_name,
        "last_name": last_name,
        "middle_name": middle_name,
        "year": year,
        "month": month,
        "day": day,
    }


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
# Outbound sync tests
# ---------------------------------------------------------------------------


class TestOutboundSyncSkipsUnlinkedContact:
    """Contacts not linked to Immich should be skipped."""

    @pytest.mark.asyncio
    async def test_returns_skipped_when_no_external_reference(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact with no link returns skipped status."""
        with patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo:
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(return_value=None)

            result = await service.sync_contact_outbound(contact_id=999)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_linked"
        mock_api_client.update_person.assert_not_called()


class TestOutboundSyncPushesNameToImmich:
    """Outbound sync should push the correct full name to Immich."""

    @pytest.mark.asyncio
    async def test_pushes_first_and_last_name(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Linked contact pushes 'First Last' name to Immich."""
        immich_person = _make_person(name="Old Name")
        updated_person = _make_person(name="John Smith")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(first_name="John", last_name="Smith")
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        mock_api_client.update_person.assert_called_once()
        call_args = mock_api_client.update_person.call_args
        assert call_args[0][0] == "person-uuid-1"
        assert call_args[0][1]["name"] == "John Smith"


class TestOutboundSyncNameFormatting:
    """Tests for name formatting with middle names and single names."""

    @pytest.mark.asyncio
    async def test_formats_name_with_middle_name(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact with middle name pushes 'First Middle Last' to Immich."""
        immich_person = _make_person(name="Old Name")
        updated_person = _make_person(name="John Michael Smith")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(
                    first_name="John", middle_name="Michael", last_name="Smith"
                )
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        assert call_args[0][1]["name"] == "John Michael Smith"

    @pytest.mark.asyncio
    async def test_handles_first_name_only(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact with only first name pushes just 'First' to Immich."""
        immich_person = _make_person(name="Old")
        updated_person = _make_person(name="Madonna")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(first_name="Madonna", last_name=None)
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        assert call_args[0][1]["name"] == "Madonna"


class TestOutboundSyncBirthdayPrecision:
    """Outbound sync should only push FULL precision birthdays."""

    @pytest.mark.asyncio
    async def test_pushes_full_precision_birthday(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact with FULL precision birthday sends birthDate to Immich."""
        immich_person = _make_person(name="John Smith")
        updated_person = _make_person(name="John Smith", birth_date="1990-05-15")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(year=1990, month=5, day=15)
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        assert call_args[0][1]["birthDate"] == "1990-05-15"

    @pytest.mark.asyncio
    async def test_skips_non_full_precision_birthday(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact without FULL precision birthday does NOT send birthDate.

        The find_contact_with_birthday query only returns full-precision
        birthdays (year, month, day). When the precision is DAY_MONTH or
        YEAR, the query returns NULLs for those fields.
        """
        immich_person = _make_person(name="John Smith")
        updated_person = _make_person(name="John Smith")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            # No year/month/day → non-full precision birthday
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(year=None, month=None, day=None)
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        # birthDate should NOT be sent when no full-precision birthday
        assert "birthDate" not in call_args[0][1]

    @pytest.mark.asyncio
    async def test_preserves_immich_birthday_when_local_null(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """When local has no FULL birthday but Immich has one, preserve Immich's.

        Source of truth enforcement: do not clear Immich's existing birthDate
        when the local contact doesn't have a full-precision birthday.
        """
        # Immich already has a birthday set
        immich_person = _make_person(name="John Smith", birth_date="1985-03-20")
        updated_person = _make_person(name="John Smith", birth_date="1985-03-20")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            # Local contact has no full-precision birthday
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(year=None, month=None, day=None)
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        # Should preserve Immich's existing birthday
        assert call_args[0][1]["birthDate"] == "1985-03-20"


class TestOutboundSyncMetadataUpdate:
    """Outbound sync should update sync metadata after successful push."""

    @pytest.mark.asyncio
    async def test_updates_sync_metadata_after_push(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
        mock_connection: AsyncMock,
    ) -> None:
        """After successful outbound push, sync metadata version hash is updated."""
        immich_person = _make_person(name="John Smith")
        updated_person = _make_person(name="John Smith")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        # We need to track the _upsert_sync_metadata call
        upsert_mock = MagicMock()
        upsert_row = MagicMock()
        upsert_row.id = 1
        upsert_mock.fetchone.return_value = upsert_row

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data()
            )

            # Mock the connection.execute for sync_metadata upsert
            mock_connection.execute = AsyncMock(return_value=upsert_mock)

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        # Verify sync_metadata was updated (connection.execute was called)
        mock_connection.execute.assert_called()


class TestOutboundSyncContactNotFound:
    """Outbound sync should handle missing contacts gracefully."""

    @pytest.mark.asyncio
    async def test_returns_error_when_contact_not_found(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Contact referenced but not found returns error status."""
        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(return_value=None)

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "error"
        assert result["reason"] == "contact_not_found"
        mock_api_client.update_person.assert_not_called()


class TestOutboundSyncSourceOfTruth:
    """Source of truth enforcement: local values always win."""

    @pytest.mark.asyncio
    async def test_local_name_overwrites_immich_name(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Local contact name overwrites the Immich person's name.

        Verifies that local is the source of truth for name data.
        """
        # Immich has a different name
        immich_person = _make_person(name="Wrong Name")
        updated_person = _make_person(name="Jane Doe")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(first_name="Jane", last_name="Doe")
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        # Local name wins, not Immich's existing name
        assert call_args[0][1]["name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_local_birthday_overwrites_immich_birthday(
        self,
        service: ImmichSyncService,
        mock_api_client: AsyncMock,
    ) -> None:
        """Local FULL birthday overwrites the Immich person's birthDate.

        Verifies that local is the source of truth for birthday data.
        """
        # Immich has a different birthday
        immich_person = _make_person(name="John Smith", birth_date="2000-01-01")
        updated_person = _make_person(name="John Smith", birth_date="1990-06-15")
        mock_api_client.get_person = AsyncMock(return_value=immich_person)
        mock_api_client.update_person = AsyncMock(return_value=updated_person)

        with (
            patch("immich_sync_service.IntegrationLinkRepository") as MockLinkRepo,
        ):
            link_instance = MockLinkRepo.return_value
            link_instance.find_external_by_internal = AsyncMock(
                return_value=_make_link_dict()
            )
            link_instance.find_contact_with_birthday = AsyncMock(
                return_value=_make_contact_data(year=1990, month=6, day=15)
            )

            result = await service.sync_contact_outbound(contact_id=42)

        assert result["status"] == "success"
        call_args = mock_api_client.update_person.call_args
        # Local birthday wins
        assert call_args[0][1]["birthDate"] == "1990-06-15"
