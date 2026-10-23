"""Tests for AddressValidationService."""

import pytest
from core_shared.models.contacts.entities import ContactAddress
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.services.address_validation_service import (
    AddressValidationService,
)


class TestAddressValidationService:
    """Test AddressValidationService."""

    @pytest.fixture
    def service(self):
        """Create AddressValidationService instance."""
        return AddressValidationService()

    def test_validate_country_code_valid_au(self, service):
        """Test valid Australian country code."""
        service.validate_country_code("AU")  # Should not raise

    def test_validate_country_code_valid_us(self, service):
        """Test valid US country code."""
        service.validate_country_code("US")  # Should not raise

    def test_validate_country_code_invalid_raises_error(self, service):
        """Test invalid country code raises error."""
        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_country_code("XX")

        assert exc_info.value.field == "country_code"
        assert "Invalid country code" in exc_info.value.message

    def test_validate_address_format_valid_address(self, service):
        """Test valid address format."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1
        )
        service.validate_address_format(address)  # Should not raise

    def test_validate_address_format_empty_street_raises_error(self, service):
        """Test empty street address raises error."""
        # The ContactAddress constructor will raise ValueError for empty street_line_1
        # So we test the service method directly with a mock address
        from unittest.mock import Mock

        address = Mock()
        address.country_code = "AU"
        address.street_line_1 = "   "  # Whitespace only
        address.postal_code = None

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "street_line_1"
        assert "Street address is required" in exc_info.value.message

    def test_validate_address_format_invalid_country_raises_error(self, service):
        """Test invalid country code raises error."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="XX", contact_id=1
        )

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "country_code"

    @pytest.mark.parametrize(
        ("country_code", "postal_code"),
        [("NL", "invalid"), ("ES", "8001"), ("SE", "1"), ("AU", "#2000.")],
        ids=["dutch", "spanish-missing-zero", "swedish", "punctuation"],
    )
    def test_any_postal_code_is_accepted(
        self, service: AddressValidationService, country_code: str, postal_code: str
    ) -> None:
        """Postcodes are not validated: a badly typed one must not fail a contact."""
        address = ContactAddress(
            street_line_1="123 Main St",
            country_code=country_code,
            postal_code=postal_code,
            contact_id=1,
        )

        service.validate_address_format(address)  # Should not raise

    @pytest.mark.parametrize(
        ("country_code", "region", "normalised"),
        [
            ("AU", "NSW", "NSW"),
            ("AU", "nsw", "NSW"),
            ("AU", "New South Wales", "NSW"),
            ("AU", "  new south wales ", "NSW"),
            ("AU", "Australian Capital Territory", "ACT"),
            ("AU", "tasmania", "TAS"),
            ("US", "ca", "CA"),
            ("US", "California", "CA"),
            ("US", "district of columbia", "DC"),
            ("CA", "on", "ON"),
            ("CA", "Québec", "QC"),
            ("CA", "quebec", "QC"),
            ("CA", "Newfoundland and Labrador", "NL"),
        ],
    )
    def test_a_known_region_is_normalised_to_its_code(
        self,
        service: AddressValidationService,
        country_code: str,
        region: str,
        normalised: str,
    ) -> None:
        assert service.normalise_region(country_code, region) == normalised

    @pytest.mark.parametrize("region", [None, "", "   "])
    def test_an_empty_region_is_none(
        self, service: AddressValidationService, region: str | None
    ) -> None:
        assert service.normalise_region("AU", region) is None

    @pytest.mark.parametrize(
        ("country_code", "region"),
        [("AU", "London"), ("US", "XX"), ("CA", "Somewhere")],
    )
    def test_an_unrecognised_region_is_kept_as_written(
        self, service: AddressValidationService, country_code: str, region: str
    ) -> None:
        """A wrong inferred country must not fail a contact (#1820)."""
        assert service.normalise_region(country_code, f" {region} ") == region

    def test_a_region_elsewhere_is_only_trimmed(
        self, service: AddressValidationService
    ) -> None:
        """Only AU, US and CA regions were ever validated, so only they map."""
        assert service.normalise_region("GB", " Greater London ") == "Greater London"

    def test_normalise_address_rewrites_the_region(
        self, service: AddressValidationService
    ) -> None:
        address = ContactAddress(
            street_line_1="1 George St",
            country_code="AU",
            region="new south wales",
            contact_id=1,
        )

        normalised = service.normalise_address(address)

        assert normalised.region == "NSW"
        assert normalised.street_line_1 == "1 George St"

    @pytest.mark.parametrize(
        ("country_code", "region"),
        [("AU", "Sydney"), ("US", "XX"), ("CA", "XX")],
    )
    def test_any_region_passes_validation(
        self, service: AddressValidationService, country_code: str, region: str
    ) -> None:
        address = ContactAddress(
            street_line_1="123 Main St",
            country_code=country_code,
            region=region,
            contact_id=1,
        )

        service.validate_address_format(address)  # Should not raise

    @pytest.mark.asyncio
    async def test_validate_with_transaction(self, service):
        """Test validation with transaction context."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1
        )
        await service.validate_with_transaction(address)  # Should not raise
