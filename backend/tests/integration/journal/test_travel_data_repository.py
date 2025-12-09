"""Integration tests for TravelDataRepository."""

from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.travel_data import (
    TravelAccommodation,
    TravelData,
    TravelFlight,
    TravelTransportation,
)


@pytest.mark.integration
class TestSqlTravelDataRepository:
    """Integration tests for SqlTravelDataRepository."""

    async def test_find_by_journal_id_not_found(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test finding travel data that doesn't exist."""
        repo = SqlTravelDataRepository(db_connection)

        result = await repo.find_by_journal_id(sample_journal_id)

        assert result is None

    async def test_save_and_find_travel_data(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding travel data."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data
        travel_data = TravelData(journal_id=sample_journal_id)

        # Save travel data
        saved = await repo.save(travel_data)

        # Verify saved data
        assert saved.journal_id == sample_journal_id
        assert saved.flights == []
        assert saved.accommodations == []
        assert saved.transportation == []
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # Find travel data
        found = await repo.find_by_journal_id(sample_journal_id)

        assert found is not None
        assert found.journal_id == sample_journal_id
        assert found.flights == []
        assert found.accommodations == []
        assert found.transportation == []
        assert found.created_at == saved.created_at
        assert found.updated_at == saved.updated_at

    async def test_save_and_find_flight(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding travel flights."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data first
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        # Create flight
        flight = TravelFlight(
            id=uuid4(),
            journal_id=sample_journal_id,
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

        # Save flight
        saved_flight = await repo.save_flight(flight)

        # Verify saved flight
        assert saved_flight.id == flight.id
        assert saved_flight.flight_number == "QF123"
        assert saved_flight.airline == "Qantas"
        assert saved_flight.departure_airport == "SYD"
        assert saved_flight.arrival_airport == "MEL"
        assert saved_flight.booking_reference == "ABC123"
        assert saved_flight.seat_number == "12A"
        assert saved_flight.confirmation_number == "XYZ789"
        assert saved_flight.created_at is not None

        # Find travel data with flights
        found_travel = await repo.find_by_journal_id(sample_journal_id)

        assert found_travel is not None
        assert len(found_travel.flights) == 1
        assert found_travel.flights[0].id == flight.id
        assert found_travel.flights[0].flight_number == "QF123"

    async def test_save_and_find_accommodation(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding travel accommodations."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data first
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        # Create accommodation
        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=sample_journal_id,
            name="Hotel Example",
            address="123 Main St, Sydney NSW 2000",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            booking_reference="HOTEL123",
            confirmation_number="CONF456",
            order=0,
        )

        # Save accommodation
        saved_accommodation = await repo.save_accommodation(accommodation)

        # Verify saved accommodation
        assert saved_accommodation.id == accommodation.id
        assert saved_accommodation.name == "Hotel Example"
        assert saved_accommodation.address == "123 Main St, Sydney NSW 2000"
        assert saved_accommodation.check_in_date == date(2024, 1, 1)
        assert saved_accommodation.check_out_date == date(2024, 1, 3)
        assert saved_accommodation.booking_reference == "HOTEL123"
        assert saved_accommodation.confirmation_number == "CONF456"
        assert saved_accommodation.created_at is not None

        # Find travel data with accommodations
        found_travel = await repo.find_by_journal_id(sample_journal_id)

        assert found_travel is not None
        assert len(found_travel.accommodations) == 1
        assert found_travel.accommodations[0].id == accommodation.id
        assert found_travel.accommodations[0].name == "Hotel Example"

    async def test_save_and_find_transportation(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving and finding travel transportation."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data first
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        # Create transportation
        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=sample_journal_id,
            type="car_rental",
            details="Compact car from Hertz, pickup at airport",
            booking_reference="CAR123",
            order=0,
        )

        # Save transportation
        saved_transportation = await repo.save_transportation(transportation)

        # Verify saved transportation
        assert saved_transportation.id == transportation.id
        assert saved_transportation.type == "car_rental"
        assert (
            saved_transportation.details == "Compact car from Hertz, pickup at airport"
        )
        assert saved_transportation.booking_reference == "CAR123"
        assert saved_transportation.created_at is not None

        # Find travel data with transportation
        found_travel = await repo.find_by_journal_id(sample_journal_id)

        assert found_travel is not None
        assert len(found_travel.transportation) == 1
        assert found_travel.transportation[0].id == transportation.id
        assert found_travel.transportation[0].type == "car_rental"

    async def test_complete_travel_itinerary(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test saving a complete travel itinerary with all components."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        # Create flight
        flight = TravelFlight(
            id=uuid4(),
            journal_id=sample_journal_id,
            flight_number="QF123",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            order=0,
        )
        await repo.save_flight(flight)

        # Create accommodation
        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=sample_journal_id,
            name="Hotel Example",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            order=0,
        )
        await repo.save_accommodation(accommodation)

        # Create transportation
        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=sample_journal_id,
            type="car_rental",
            details="Compact car",
            order=0,
        )
        await repo.save_transportation(transportation)

        # Find complete travel data
        found_travel = await repo.find_by_journal_id(sample_journal_id)

        assert found_travel is not None
        assert len(found_travel.flights) == 1
        assert len(found_travel.accommodations) == 1
        assert len(found_travel.transportation) == 1

        # Verify all components
        assert found_travel.flights[0].flight_number == "QF123"
        assert found_travel.accommodations[0].name == "Hotel Example"
        assert found_travel.transportation[0].type == "car_rental"

    async def test_delete_flight(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting a flight."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data and flight
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        flight = TravelFlight(
            id=uuid4(),
            journal_id=sample_journal_id,
            flight_number="QF123",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            order=0,
        )
        await repo.save_flight(flight)

        # Verify flight exists
        found_travel = await repo.find_by_journal_id(sample_journal_id)
        assert found_travel is not None
        assert len(found_travel.flights) == 1

        # Delete flight
        await repo.delete_flight(flight.id)

        # Verify flight is deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is not None
        assert len(found_after_delete.flights) == 0

    async def test_delete_accommodation(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting an accommodation."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data and accommodation
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=sample_journal_id,
            name="Hotel Example",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            order=0,
        )
        await repo.save_accommodation(accommodation)

        # Verify accommodation exists
        found_travel = await repo.find_by_journal_id(sample_journal_id)
        assert found_travel is not None
        assert len(found_travel.accommodations) == 1

        # Delete accommodation
        await repo.delete_accommodation(accommodation.id)

        # Verify accommodation is deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is not None
        assert len(found_after_delete.accommodations) == 0

    async def test_delete_transportation(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test deleting transportation."""
        repo = SqlTravelDataRepository(db_connection)

        # Create travel data and transportation
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=sample_journal_id,
            type="car_rental",
            details="Compact car",
            order=0,
        )
        await repo.save_transportation(transportation)

        # Verify transportation exists
        found_travel = await repo.find_by_journal_id(sample_journal_id)
        assert found_travel is not None
        assert len(found_travel.transportation) == 1

        # Delete transportation
        await repo.delete_transportation(transportation.id)

        # Verify transportation is deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is not None
        assert len(found_after_delete.transportation) == 0

    async def test_delete_travel_data_cascades_components(
        self, db_connection: AsyncConnection, sample_journal_id: int
    ):
        """Test that deleting travel data also deletes all associated components."""
        repo = SqlTravelDataRepository(db_connection)

        # Create complete travel data
        travel_data = TravelData(journal_id=sample_journal_id)
        await repo.save(travel_data)

        # Add all types of components
        flight = TravelFlight(
            id=uuid4(),
            journal_id=sample_journal_id,
            flight_number="QF123",
            departure_airport="SYD",
            arrival_airport="MEL",
            departure_time=datetime(2024, 1, 1, 10, 0),
            arrival_time=datetime(2024, 1, 1, 11, 30),
            order=0,
        )
        await repo.save_flight(flight)

        accommodation = TravelAccommodation(
            id=uuid4(),
            journal_id=sample_journal_id,
            name="Hotel Example",
            check_in_date=date(2024, 1, 1),
            check_out_date=date(2024, 1, 3),
            order=0,
        )
        await repo.save_accommodation(accommodation)

        transportation = TravelTransportation(
            id=uuid4(),
            journal_id=sample_journal_id,
            type="car_rental",
            details="Compact car",
            order=0,
        )
        await repo.save_transportation(transportation)

        # Verify all components exist
        found_travel = await repo.find_by_journal_id(sample_journal_id)
        assert found_travel is not None
        assert len(found_travel.flights) == 1
        assert len(found_travel.accommodations) == 1
        assert len(found_travel.transportation) == 1

        # Delete travel data
        await repo.delete(sample_journal_id)

        # Verify travel data and all components are deleted
        found_after_delete = await repo.find_by_journal_id(sample_journal_id)
        assert found_after_delete is None
