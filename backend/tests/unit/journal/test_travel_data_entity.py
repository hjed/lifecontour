"""Unit tests for TravelData and related entities (TRAVEL type)."""

from datetime import date, datetime
from uuid import uuid4

import pytest
from core_shared.models.journals import (
    MAX_ACCOMMODATION_NAME_LENGTH,
    MAX_AIRLINE_LENGTH,
    MAX_BOOKING_REFERENCE_LENGTH,
    MAX_FLIGHT_NUMBER_LENGTH,
    MAX_TRANSPORTATION_TYPE_LENGTH,
    TravelAccommodation,
    TravelAccommodationValidationError,
    TravelData,
    TravelDataValidationError,
    TravelFlight,
    TravelFlightValidationError,
    TravelTransportation,
    TravelTransportationValidationError,
)


@pytest.mark.unit
class TestTravelData:
    """Test TravelData entity."""

    def test_create_travel_data_minimal(self):
        """Test creating travel data with minimal required fields."""
        travel_data = TravelData(journal_id=1)

        assert travel_data.journal_id == 1
        assert travel_data.flights == []
        assert travel_data.accommodations == []
        assert travel_data.transportation == []

    def test_create_travel_data_with_components(self):
        """Test creating travel data with all components."""
        flight = TravelFlight(
            id=uuid4(),
            journal_id=1,
            flight_number="QF123",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            order=0,
        )
        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=1,
            name="Hotel Example",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            order=0,
        )
        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=1,
            type="car_rental",
            details="Compact car from Hertz",
            order=0,
        )

        travel_data = TravelData(
            journal_id=1,
            flights=[flight],
            accommodations=[accommodation],
            transportation=[transportation],
        )

        assert len(travel_data.flights) == 1
        assert len(travel_data.accommodations) == 1
        assert len(travel_data.transportation) == 1


@pytest.mark.unit
class TestTravelDataValidation:
    """Test TravelData validation."""

    def test_invalid_journal_id_zero_raises_error(self):
        """Test that journal_id of 0 raises error."""
        with pytest.raises(
            TravelDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            TravelData(journal_id=0)

    def test_invalid_journal_id_negative_raises_error(self):
        """Test that negative journal_id raises error."""
        with pytest.raises(
            TravelDataValidationError,
            match="Journal ID must be a positive integer",
        ):
            TravelData(journal_id=-1)


@pytest.mark.unit
class TestTravelFlight:
    """Test TravelFlight entity."""

    def test_create_travel_flight_minimal(self):
        """Test creating travel flight with minimal required fields."""
        flight = TravelFlight(
            id=uuid4(),
            journal_id=1,
            flight_number="QF123",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            order=0,
        )

        assert flight.journal_id == 1
        assert flight.flight_number == "QF123"
        assert flight.departure_airport == "SYD"
        assert flight.arrival_airport == "MEL"
        assert flight.airline is None
        assert flight.booking_reference is None

    def test_create_travel_flight_with_all_fields(self):
        """Test creating travel flight with all fields."""
        flight = TravelFlight(
            id=uuid4(),
            journal_id=1,
            flight_number="QF123",
            airline="Qantas",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            booking_reference="ABC123",
            seat_number="12A",
            confirmation_number="XYZ789",
            order=0,
        )

        assert flight.airline == "Qantas"
        assert flight.booking_reference == "ABC123"
        assert flight.seat_number == "12A"
        assert flight.confirmation_number == "XYZ789"


@pytest.mark.unit
class TestTravelFlightValidation:
    """Test TravelFlight validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            TravelFlightValidationError,
            match="Journal ID must be a positive integer",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=0,
                flight_number="QF123",
                departure_airport="SYD",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 10, 0),
                arrival_time=datetime(2024, 1, 1, 11, 30),
                order=0,
            )

    def test_empty_flight_number_raises_error(self):
        """Test that empty flight number raises error."""
        with pytest.raises(
            TravelFlightValidationError,
            match="Flight number is required",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=1,
                flight_number="",
                departure_airport="SYD",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 10, 0),
                arrival_time=datetime(2024, 1, 1, 11, 30),
                order=0,
            )

    def test_flight_number_too_long_raises_error(self):
        """Test that flight number exceeding max length raises error."""
        long_flight_number = "A" * (MAX_FLIGHT_NUMBER_LENGTH + 1)
        with pytest.raises(
            TravelFlightValidationError,
            match=f"Flight number cannot exceed {MAX_FLIGHT_NUMBER_LENGTH}",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=1,
                flight_number=long_flight_number,
                departure_airport="SYD",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 10, 0),
                arrival_time=datetime(2024, 1, 1, 11, 30),
                order=0,
            )

    def test_empty_departure_airport_raises_error(self):
        """Test that empty departure airport raises error."""
        with pytest.raises(
            TravelFlightValidationError,
            match="Departure airport is required",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=1,
                flight_number="QF123",
                departure_airport="",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 10, 0),
                arrival_time=datetime(2024, 1, 1, 11, 30),
                order=0,
            )

    def test_arrival_time_before_departure_raises_error(self):
        """Test that arrival time before departure time raises error."""
        with pytest.raises(
            TravelFlightValidationError,
            match="Arrival time must be after departure time",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=1,
                flight_number="QF123",
                departure_airport="SYD",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 11, 30),
                arrival_time=datetime(2024, 1, 1, 10, 0),  # Before departure
                order=0,
            )

    def test_airline_too_long_raises_error(self):
        """Test that airline exceeding max length raises error."""
        long_airline = "A" * (MAX_AIRLINE_LENGTH + 1)
        with pytest.raises(
            TravelFlightValidationError,
            match=f"Airline cannot exceed {MAX_AIRLINE_LENGTH}",
        ):
            TravelFlight(
                id=uuid4(),
                journal_id=1,
                flight_number="QF123",
                airline=long_airline,
                departure_airport="SYD",
                arrival_airport="MEL",
                departure_time=datetime(2024, 1, 1, 10, 0),
                arrival_time=datetime(2024, 1, 1, 11, 30),
                order=0,
            )


@pytest.mark.unit
class TestTravelAccommodation:
    """Test TravelAccommodation entity."""

    def test_create_travel_accommodation_minimal(self):
        """Test creating travel accommodation with minimal required fields."""
        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=1,
            name="Hotel Example",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            order=0,
        )

        assert accommodation.journal_id == 1
        assert accommodation.name == "Hotel Example"
        assert accommodation.check_in_date == date(2024, 1, 1)
        assert accommodation.check_out_date == date(2024, 1, 3)
        assert accommodation.address is None
        assert accommodation.booking_reference is None

    def test_create_travel_accommodation_with_all_fields(self):
        """Test creating travel accommodation with all fields."""
        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=1,
            name="Hotel Example",
            address="123 Main St, Sydney NSW 2000",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            booking_reference="HOTEL123",
            confirmation_number="CONF456",
            order=0,
        )

        assert accommodation.address == "123 Main St, Sydney NSW 2000"
        assert accommodation.booking_reference == "HOTEL123"
        assert accommodation.confirmation_number == "CONF456"


@pytest.mark.unit
class TestTravelAccommodationValidation:
    """Test TravelAccommodation validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            TravelAccommodationValidationError,
            match="Journal ID must be a positive integer",
        ):
            TravelAccommodation(
                id=uuid4(),
                journal_id=0,
                name="Hotel Example",
                check_in_date=date(2024, 1, 1),
                check_out_date=date(2024, 1, 3),
                order=0,
            )

    def test_empty_name_raises_error(self):
        """Test that empty name raises error."""
        with pytest.raises(
            TravelAccommodationValidationError,
            match="Accommodation name is required",
        ):
            TravelAccommodation(
                id=uuid4(),
                journal_id=1,
                name="",
                check_in_date=date(2024, 1, 1),
                check_out_date=date(2024, 1, 3),
                order=0,
            )

    def test_name_too_long_raises_error(self):
        """Test that name exceeding max length raises error."""
        long_name = "A" * (MAX_ACCOMMODATION_NAME_LENGTH + 1)
        with pytest.raises(
            TravelAccommodationValidationError,
            match=f"Accommodation name cannot exceed {MAX_ACCOMMODATION_NAME_LENGTH}",
        ):
            TravelAccommodation(
                id=uuid4(),
                journal_id=1,
                name=long_name,
                check_in_date=date(2024, 1, 1),
                check_out_date=date(2024, 1, 3),
                order=0,
            )

    def test_check_out_before_check_in_raises_error(self):
        """Test that check-out date before check-in date raises error."""
        with pytest.raises(
            TravelAccommodationValidationError,
            match="Check-out date must be after check-in date",
        ):
            TravelAccommodation(
                id=uuid4(),
                journal_id=1,
                name="Hotel Example",
                check_in_date=date(2024, 1, 3),
                check_out_date=date(2024, 1, 1),  # Before check-in
                order=0,
            )


@pytest.mark.unit
class TestTravelTransportation:
    """Test TravelTransportation entity."""

    def test_create_travel_transportation_minimal(self):
        """Test creating travel transportation with minimal required fields."""
        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=1,
            type="car_rental",
            details="Compact car from Hertz",
            order=0,
        )

        assert transportation.journal_id == 1
        assert transportation.type == "car_rental"
        assert transportation.details == "Compact car from Hertz"
        assert transportation.booking_reference is None

    def test_create_travel_transportation_with_booking_reference(self):
        """Test creating travel transportation with booking reference."""
        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=1,
            type="train",
            details="Express train from Sydney to Melbourne",
            booking_reference="TRAIN123",
            order=0,
        )

        assert transportation.booking_reference == "TRAIN123"


@pytest.mark.unit
class TestTravelTransportationValidation:
    """Test TravelTransportation validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        with pytest.raises(
            TravelTransportationValidationError,
            match="Journal ID must be a positive integer",
        ):
            TravelTransportation(
                id=uuid4(),
                journal_id=0,
                type="car_rental",
                details="Compact car",
                order=0,
            )

    def test_empty_type_raises_error(self):
        """Test that empty type raises error."""
        with pytest.raises(
            TravelTransportationValidationError,
            match="Transportation type is required",
        ):
            TravelTransportation(
                id=uuid4(),
                journal_id=1,
                type="",
                details="Compact car",
                order=0,
            )

    def test_type_too_long_raises_error(self):
        """Test that type exceeding max length raises error."""
        long_type = "A" * (MAX_TRANSPORTATION_TYPE_LENGTH + 1)
        with pytest.raises(
            TravelTransportationValidationError,
            match=f"Transportation type cannot exceed {MAX_TRANSPORTATION_TYPE_LENGTH}",
        ):
            TravelTransportation(
                id=uuid4(),
                journal_id=1,
                type=long_type,
                details="Compact car",
                order=0,
            )

    def test_empty_details_raises_error(self):
        """Test that empty details raises error."""
        with pytest.raises(
            TravelTransportationValidationError,
            match="Transportation details are required",
        ):
            TravelTransportation(
                id=uuid4(),
                journal_id=1,
                type="car_rental",
                details="",
                order=0,
            )

    def test_booking_reference_too_long_raises_error(self):
        """Test that booking reference exceeding max length raises error."""
        long_booking_ref = "A" * (MAX_BOOKING_REFERENCE_LENGTH + 1)
        with pytest.raises(
            TravelTransportationValidationError,
            match=f"Booking reference cannot exceed {MAX_BOOKING_REFERENCE_LENGTH}",
        ):
            TravelTransportation(
                id=uuid4(),
                journal_id=1,
                type="car_rental",
                details="Compact car",
                booking_reference=long_booking_ref,
                order=0,
            )
