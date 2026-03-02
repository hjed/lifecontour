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

    def test_validate_postal_code_empty_allowed(self, service):
        """Test empty postal code is allowed."""
        service.validate_postal_code("", "AU")  # Should not raise

    def test_validate_postal_code_none_allowed(self, service):
        """Test None postal code is allowed."""
        service.validate_postal_code(None, "AU")  # Should not raise

    def test_validate_postal_code_dutch_valid(self, service):
        """Test valid Dutch postal code."""
        service.validate_postal_code("1234AB", "NL")  # Should not raise

    def test_validate_postal_code_dutch_invalid_raises_error(self, service):
        """Test invalid Dutch postal code raises error."""
        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_postal_code("invalid", "NL")

        assert exc_info.value.field == "postal_code"
        assert "Invalid Dutch postal code" in exc_info.value.message

    def test_validate_postal_code_swedish_valid(self, service):
        """Test valid Swedish postal code."""
        service.validate_postal_code("12345", "SE")  # Should not raise

    def test_validate_postal_code_spanish_valid(self, service):
        """Test valid Spanish postal code."""
        service.validate_postal_code("12345", "ES")  # Should not raise

    def test_validate_postal_code_spanish_invalid_raises_error(self, service):
        """Test invalid Spanish postal code raises error."""
        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_postal_code("1234", "ES")  # Too short

        assert exc_info.value.field == "postal_code"
        assert "Invalid Spanish postal code" in exc_info.value.message

    def test_validate_postal_code_unknown_country_basic_validation(self, service):
        """Test postal code validation for unknown country uses basic validation."""
        service.validate_postal_code("12345", "ZZ")  # Should not raise
        service.validate_postal_code("ABC-123", "ZZ")  # Should not raise

    def test_validate_postal_code_unknown_country_invalid_raises_error(self, service):
        """Test invalid postal code for unknown country raises error."""
        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_postal_code("invalid@#$", "ZZ")

        assert exc_info.value.field == "postal_code"
        assert "Invalid postal code format" in exc_info.value.message

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

    def test_validate_address_format_with_postal_code(self, service):
        """Test address validation with postal code."""
        address = ContactAddress(
            street_line_1="123 Main St",
            country_code="NL",
            postal_code="1234AB",
            contact_id=1,
        )
        service.validate_address_format(address)  # Should not raise

    def test_validate_address_format_invalid_postal_code_raises_error(self, service):
        """Test invalid postal code raises error."""
        address = ContactAddress(
            street_line_1="123 Main St",
            country_code="NL",
            postal_code="invalid",
            contact_id=1,
        )

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "postal_code"

    def test_validate_country_specific_rules_au_valid_state(self, service):
        """Test Australian state validation."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", region="NSW", contact_id=1
        )
        service.validate_address_format(address)  # Should not raise

    def test_validate_country_specific_rules_au_invalid_state_raises_error(
        self, service
    ):
        """Test invalid Australian state raises error."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", region="XX", contact_id=1
        )

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "region"
        assert "Invalid Australian state/territory" in exc_info.value.message

    def test_validate_country_specific_rules_us_valid_state(self, service):
        """Test US state validation."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="US", region="CA", contact_id=1
        )
        service.validate_address_format(address)  # Should not raise

    def test_validate_country_specific_rules_us_invalid_state_raises_error(
        self, service
    ):
        """Test invalid US state raises error."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="US", region="XX", contact_id=1
        )

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "region"
        assert "Invalid US state code" in exc_info.value.message

    def test_validate_country_specific_rules_ca_valid_province(self, service):
        """Test Canadian province validation."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="CA", region="ON", contact_id=1
        )
        service.validate_address_format(address)  # Should not raise

    def test_validate_country_specific_rules_ca_invalid_province_raises_error(
        self, service
    ):
        """Test invalid Canadian province raises error."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="CA", region="XX", contact_id=1
        )

        with pytest.raises(ContactValidationError) as exc_info:
            service.validate_address_format(address)

        assert exc_info.value.field == "region"
        assert "Invalid Canadian province/territory" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_validate_with_transaction(self, service):
        """Test validation with transaction context."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1
        )
        await service.validate_with_transaction(address)  # Should not raise
