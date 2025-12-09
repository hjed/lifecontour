"""SQL implementation of TravelDataRepository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.exceptions import (
    TravelAccommodationValidationError,
    TravelDataValidationError,
    TravelFlightValidationError,
    TravelTransportationValidationError,
)
from app.core.journal.models.repositories import TravelDataRepository
from app.core.journal.models.travel_data import (
    TravelAccommodation,
    TravelData,
    TravelFlight,
    TravelTransportation,
)


class SqlTravelDataRepository(TravelDataRepository):
    """
    SQL implementation of TravelDataRepository using SQLAlchemy Core.

    Uses explicit SQL queries for clarity and performance.
    Handles the journal_travel_data and related tables operations.
    """

    def __init__(self, connection: AsyncConnection):
        """
        Initialize the repository with a database connection.

        Args:
            connection: SQLAlchemy async connection
        """
        self.connection = connection

    async def find_by_journal_id(self, journal_id: int) -> TravelData | None:
        """
        Find travel data by journal ID, including all associated components.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The TravelData with all components if found (journal has TRAVEL type), None otherwise
        """
        # First check if travel data exists
        travel_query = text("""
            SELECT journal_id, created_at, updated_at
            FROM journal_travel_data
            WHERE journal_id = :journal_id
        """)

        result = await self.connection.execute(travel_query, {"journal_id": journal_id})
        travel_row = result.fetchone()

        if travel_row is None:
            return None

        # Get all associated components
        flights = await self._get_flights(journal_id)
        accommodations = await self._get_accommodations(journal_id)
        transportation = await self._get_transportation(journal_id)

        return TravelData(
            journal_id=travel_row.journal_id,
            flights=flights,
            accommodations=accommodations,
            transportation=transportation,
            created_at=travel_row.created_at,
            updated_at=travel_row.updated_at,
        )

    async def save(self, travel_data: TravelData) -> TravelData:
        """
        Save travel data (insert or update).

        This effectively adds or updates the TRAVEL type for a journal.
        Components are saved separately.

        Args:
            travel_data: The travel data to save

        Returns:
            The saved travel data with updated timestamps

        Raises:
            TravelDataValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        # Check if record exists
        existing = await self.find_by_journal_id(travel_data.journal_id)

        try:
            if existing is None:
                # Insert new record
                query = text("""
                    INSERT INTO journal_travel_data 
                    (journal_id, created_at, updated_at)
                    VALUES (:journal_id, :created_at, :updated_at)
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": travel_data.journal_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                return TravelData(
                    journal_id=travel_data.journal_id,
                    flights=travel_data.flights,
                    accommodations=travel_data.accommodations,
                    transportation=travel_data.transportation,
                    created_at=now,
                    updated_at=now,
                )
            else:
                # Update existing record
                query = text("""
                    UPDATE journal_travel_data
                    SET updated_at = :updated_at
                    WHERE journal_id = :journal_id
                """)

                await self.connection.execute(
                    query,
                    {
                        "journal_id": travel_data.journal_id,
                        "updated_at": now,
                    },
                )

                return TravelData(
                    journal_id=travel_data.journal_id,
                    flights=travel_data.flights,
                    accommodations=travel_data.accommodations,
                    transportation=travel_data.transportation,
                    created_at=existing.created_at,
                    updated_at=now,
                )

        except IntegrityError as e:
            raise TravelDataValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete(self, journal_id: int) -> None:
        """
        Delete travel data by journal ID.

        This effectively removes the TRAVEL type from a journal.
        Associated components are cascade deleted.

        Args:
            journal_id: The journal ID to delete travel data for
        """
        query = text("""
            DELETE FROM journal_travel_data
            WHERE journal_id = :journal_id
        """)

        await self.connection.execute(query, {"journal_id": journal_id})

    async def save_flight(self, flight: TravelFlight) -> TravelFlight:
        """
        Save a travel flight (insert or update).

        Args:
            flight: The travel flight to save

        Returns:
            The saved travel flight with updated timestamps

        Raises:
            TravelFlightValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        try:
            # Use UPSERT (INSERT ... ON CONFLICT) for PostgreSQL
            query = text("""
                INSERT INTO journal_travel_flights
                (id, journal_id, flight_number, airline, departure_airport, arrival_airport,
                 departure_time, arrival_time, booking_reference, seat_number,
                 confirmation_number, "order", created_at)
                VALUES (:id, :journal_id, :flight_number, :airline, :departure_airport,
                        :arrival_airport, :departure_time, :arrival_time, :booking_reference,
                        :seat_number, :confirmation_number, :order, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    flight_number = EXCLUDED.flight_number,
                    airline = EXCLUDED.airline,
                    departure_airport = EXCLUDED.departure_airport,
                    arrival_airport = EXCLUDED.arrival_airport,
                    departure_time = EXCLUDED.departure_time,
                    arrival_time = EXCLUDED.arrival_time,
                    booking_reference = EXCLUDED.booking_reference,
                    seat_number = EXCLUDED.seat_number,
                    confirmation_number = EXCLUDED.confirmation_number,
                    "order" = EXCLUDED."order"
            """)

            await self.connection.execute(
                query,
                {
                    "id": flight.id,
                    "journal_id": flight.journal_id,
                    "flight_number": flight.flight_number,
                    "airline": flight.airline,
                    "departure_airport": flight.departure_airport,
                    "arrival_airport": flight.arrival_airport,
                    "departure_time": flight.departure_time,
                    "arrival_time": flight.arrival_time,
                    "booking_reference": flight.booking_reference,
                    "seat_number": flight.seat_number,
                    "confirmation_number": flight.confirmation_number,
                    "order": flight.order,
                    "created_at": flight.created_at or now,
                },
            )

            return TravelFlight(
                id=flight.id,
                journal_id=flight.journal_id,
                flight_number=flight.flight_number,
                airline=flight.airline,
                departure_airport=flight.departure_airport,
                arrival_airport=flight.arrival_airport,
                departure_time=flight.departure_time,
                arrival_time=flight.arrival_time,
                booking_reference=flight.booking_reference,
                seat_number=flight.seat_number,
                confirmation_number=flight.confirmation_number,
                order=flight.order,
                created_at=flight.created_at or now,
            )

        except IntegrityError as e:
            raise TravelFlightValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete_flight(self, flight_id: UUID) -> None:
        """
        Delete a travel flight by ID.

        Args:
            flight_id: The flight UUID to delete
        """
        query = text("""
            DELETE FROM journal_travel_flights
            WHERE id = :flight_id
        """)

        await self.connection.execute(query, {"flight_id": flight_id})

    async def save_accommodation(self, accommodation: TravelAccommodation) -> TravelAccommodation:
        """
        Save a travel accommodation (insert or update).

        Args:
            accommodation: The travel accommodation to save

        Returns:
            The saved travel accommodation with updated timestamps

        Raises:
            TravelAccommodationValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        try:
            # Use UPSERT (INSERT ... ON CONFLICT) for PostgreSQL
            query = text("""
                INSERT INTO journal_travel_accommodations
                (id, journal_id, name, address, check_in_date, check_out_date,
                 booking_reference, confirmation_number, "order", created_at)
                VALUES (:id, :journal_id, :name, :address, :check_in_date, :check_out_date,
                        :booking_reference, :confirmation_number, :order, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    address = EXCLUDED.address,
                    check_in_date = EXCLUDED.check_in_date,
                    check_out_date = EXCLUDED.check_out_date,
                    booking_reference = EXCLUDED.booking_reference,
                    confirmation_number = EXCLUDED.confirmation_number,
                    "order" = EXCLUDED."order"
            """)

            await self.connection.execute(
                query,
                {
                    "id": accommodation.id,
                    "journal_id": accommodation.journal_id,
                    "name": accommodation.name,
                    "address": accommodation.address,
                    "check_in_date": accommodation.check_in_date,
                    "check_out_date": accommodation.check_out_date,
                    "booking_reference": accommodation.booking_reference,
                    "confirmation_number": accommodation.confirmation_number,
                    "order": accommodation.order,
                    "created_at": accommodation.created_at or now,
                },
            )

            return TravelAccommodation(
                id=accommodation.id,
                journal_id=accommodation.journal_id,
                name=accommodation.name,
                address=accommodation.address,
                check_in_date=accommodation.check_in_date,
                check_out_date=accommodation.check_out_date,
                booking_reference=accommodation.booking_reference,
                confirmation_number=accommodation.confirmation_number,
                order=accommodation.order,
                created_at=accommodation.created_at or now,
            )

        except IntegrityError as e:
            raise TravelAccommodationValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete_accommodation(self, accommodation_id: UUID) -> None:
        """
        Delete a travel accommodation by ID.

        Args:
            accommodation_id: The accommodation UUID to delete
        """
        query = text("""
            DELETE FROM journal_travel_accommodations
            WHERE id = :accommodation_id
        """)

        await self.connection.execute(query, {"accommodation_id": accommodation_id})

    async def save_transportation(self, transportation: TravelTransportation) -> TravelTransportation:
        """
        Save a travel transportation (insert or update).

        Args:
            transportation: The travel transportation to save

        Returns:
            The saved travel transportation with updated timestamps

        Raises:
            TravelTransportationValidationError: If database constraints are violated
        """
        now = datetime.utcnow()

        try:
            # Use UPSERT (INSERT ... ON CONFLICT) for PostgreSQL
            query = text("""
                INSERT INTO journal_travel_transportation
                (id, journal_id, type, details, booking_reference, "order", created_at)
                VALUES (:id, :journal_id, :type, :details, :booking_reference, :order, :created_at)
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    details = EXCLUDED.details,
                    booking_reference = EXCLUDED.booking_reference,
                    "order" = EXCLUDED."order"
            """)

            await self.connection.execute(
                query,
                {
                    "id": transportation.id,
                    "journal_id": transportation.journal_id,
                    "type": transportation.type,
                    "details": transportation.details,
                    "booking_reference": transportation.booking_reference,
                    "order": transportation.order,
                    "created_at": transportation.created_at or now,
                },
            )

            return TravelTransportation(
                id=transportation.id,
                journal_id=transportation.journal_id,
                type=transportation.type,
                details=transportation.details,
                booking_reference=transportation.booking_reference,
                order=transportation.order,
                created_at=transportation.created_at or now,
            )

        except IntegrityError as e:
            raise TravelTransportationValidationError(
                "database", f"Database constraint violation: {e}"
            ) from e

    async def delete_transportation(self, transportation_id: UUID) -> None:
        """
        Delete a travel transportation by ID.

        Args:
            transportation_id: The transportation UUID to delete
        """
        query = text("""
            DELETE FROM journal_travel_transportation
            WHERE id = :transportation_id
        """)

        await self.connection.execute(query, {"transportation_id": transportation_id})

    async def _get_flights(self, journal_id: int) -> list[TravelFlight]:
        """Get all flights for a travel journal, ordered by order field."""
        query = text("""
            SELECT id, journal_id, flight_number, airline, departure_airport, arrival_airport,
                   departure_time, arrival_time, booking_reference, seat_number,
                   confirmation_number, "order", created_at
            FROM journal_travel_flights
            WHERE journal_id = :journal_id
            ORDER BY "order", departure_time
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [
            TravelFlight(
                id=row.id,
                journal_id=row.journal_id,
                flight_number=row.flight_number,
                airline=row.airline,
                departure_airport=row.departure_airport,
                arrival_airport=row.arrival_airport,
                departure_time=row.departure_time,
                arrival_time=row.arrival_time,
                booking_reference=row.booking_reference,
                seat_number=row.seat_number,
                confirmation_number=row.confirmation_number,
                order=row.order,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def _get_accommodations(self, journal_id: int) -> list[TravelAccommodation]:
        """Get all accommodations for a travel journal, ordered by order field."""
        query = text("""
            SELECT id, journal_id, name, address, check_in_date, check_out_date,
                   booking_reference, confirmation_number, "order", created_at
            FROM journal_travel_accommodations
            WHERE journal_id = :journal_id
            ORDER BY "order", check_in_date
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [
            TravelAccommodation(
                id=row.id,
                journal_id=row.journal_id,
                name=row.name,
                address=row.address,
                check_in_date=row.check_in_date,
                check_out_date=row.check_out_date,
                booking_reference=row.booking_reference,
                confirmation_number=row.confirmation_number,
                order=row.order,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def _get_transportation(self, journal_id: int) -> list[TravelTransportation]:
        """Get all transportation for a travel journal, ordered by order field."""
        query = text("""
            SELECT id, journal_id, type, details, booking_reference, "order", created_at
            FROM journal_travel_transportation
            WHERE journal_id = :journal_id
            ORDER BY "order", created_at
        """)

        result = await self.connection.execute(query, {"journal_id": journal_id})
        rows = result.fetchall()

        return [
            TravelTransportation(
                id=row.id,
                journal_id=row.journal_id,
                type=row.type,
                details=row.details,
                booking_reference=row.booking_reference,
                order=row.order,
                created_at=row.created_at,
            )
            for row in rows
        ]
