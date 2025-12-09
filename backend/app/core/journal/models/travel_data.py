"""TravelData and related entities for the journal domain.

TravelData represents the TRAVEL journal type data. A journal has the TRAVEL type if a
row exists in the journal_travel_data table.

Related entities (TravelFlight, TravelAccommodation, TravelTransportation) represent
individual travel components stored in separate tables with ordering support.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from .constants import (
    MAX_ACCOMMODATION_NAME_LENGTH,
    MAX_AIRLINE_LENGTH,
    MAX_AIRPORT_CODE_LENGTH,
    MAX_BOOKING_REFERENCE_LENGTH,
    MAX_CONFIRMATION_NUMBER_LENGTH,
    MAX_FLIGHT_NUMBER_LENGTH,
    MAX_SEAT_NUMBER_LENGTH,
    MAX_TRANSPORTATION_TYPE_LENGTH,
)
from .exceptions import (
    TravelAccommodationValidationError,
    TravelDataValidationError,
    TravelFlightValidationError,
    TravelTransportationValidationError,
)

# Validation message constants
JOURNAL_ID_VALIDATION_MSG = "Journal ID must be a positive integer"


@dataclass
class TravelFlight:
    """
    TravelFlight entity for individual flights within a TRAVEL type journal.

    Represents flight information stored in journal_travel_flights table.
    Flights are ordered within a travel journal using the order field.

    Attributes:
        id: Unique identifier for the flight (UUID)
        journal_id: Foreign key to the journal
        flight_number: Flight number (required)
        airline: Airline name (optional)
        departure_airport: Departure airport code (required)
        arrival_airport: Arrival airport code (required)
        departure_time: Departure timestamp (required)
        arrival_time: Arrival timestamp (required)
        booking_reference: Booking reference (optional)
        seat_number: Seat number (optional)
        confirmation_number: Confirmation number (optional)
        order: Order within the travel plan (for sorting)
        created_at: Creation timestamp
    """

    id: UUID
    journal_id: int
    flight_number: str
    departure_airport: str
    arrival_airport: str
    departure_time: datetime
    arrival_time: datetime
    order: int
    airline: str | None = None
    booking_reference: str | None = None
    seat_number: str | None = None
    confirmation_number: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate travel flight properties."""
        self._validate_journal_id()
        self._validate_flight_number()
        self._validate_airports()
        self._validate_times()
        self._validate_optional_fields()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise TravelFlightValidationError(
                "journal_id", JOURNAL_ID_VALIDATION_MSG
            )

    def _validate_flight_number(self) -> None:
        """Validate flight number is provided and within length limit."""
        if not self.flight_number or not self.flight_number.strip():
            raise TravelFlightValidationError("flight_number", "Flight number is required")

        if len(self.flight_number) > MAX_FLIGHT_NUMBER_LENGTH:
            raise TravelFlightValidationError(
                "flight_number",
                f"Flight number cannot exceed {MAX_FLIGHT_NUMBER_LENGTH} characters",
            )

    def _validate_airports(self) -> None:
        """Validate airport codes are provided and within length limits."""
        if not self.departure_airport or not self.departure_airport.strip():
            raise TravelFlightValidationError(
                "departure_airport", "Departure airport is required"
            )

        if not self.arrival_airport or not self.arrival_airport.strip():
            raise TravelFlightValidationError(
                "arrival_airport", "Arrival airport is required"
            )

        if len(self.departure_airport) > MAX_AIRPORT_CODE_LENGTH:
            raise TravelFlightValidationError(
                "departure_airport",
                f"Departure airport cannot exceed {MAX_AIRPORT_CODE_LENGTH} characters",
            )

        if len(self.arrival_airport) > MAX_AIRPORT_CODE_LENGTH:
            raise TravelFlightValidationError(
                "arrival_airport",
                f"Arrival airport cannot exceed {MAX_AIRPORT_CODE_LENGTH} characters",
            )

    def _validate_times(self) -> None:
        """Validate departure and arrival times."""
        if self.departure_time >= self.arrival_time:
            raise TravelFlightValidationError(
                "arrival_time", "Arrival time must be after departure time"
            )

    def _validate_optional_fields(self) -> None:
        """Validate optional fields are within length limits."""
        if self.airline and len(self.airline) > MAX_AIRLINE_LENGTH:
            raise TravelFlightValidationError(
                "airline", f"Airline cannot exceed {MAX_AIRLINE_LENGTH} characters"
            )

        if (
            self.booking_reference
            and len(self.booking_reference) > MAX_BOOKING_REFERENCE_LENGTH
        ):
            raise TravelFlightValidationError(
                "booking_reference",
                f"Booking reference cannot exceed {MAX_BOOKING_REFERENCE_LENGTH} characters",
            )

        if self.seat_number and len(self.seat_number) > MAX_SEAT_NUMBER_LENGTH:
            raise TravelFlightValidationError(
                "seat_number",
                f"Seat number cannot exceed {MAX_SEAT_NUMBER_LENGTH} characters",
            )

        if (
            self.confirmation_number
            and len(self.confirmation_number) > MAX_CONFIRMATION_NUMBER_LENGTH
        ):
            raise TravelFlightValidationError(
                "confirmation_number",
                f"Confirmation number cannot exceed {MAX_CONFIRMATION_NUMBER_LENGTH} characters",
            )


@dataclass
class TravelAccommodation:
    """
    TravelAccommodation entity for individual accommodations within a TRAVEL type journal.

    Represents accommodation information stored in journal_travel_accommodations table.
    Accommodations are ordered within a travel journal using the order field.

    Attributes:
        id: Unique identifier for the accommodation (UUID)
        journal_id: Foreign key to the journal
        name: Accommodation name (required)
        address: Accommodation address (optional)
        check_in_date: Check-in date (required)
        check_out_date: Check-out date (required)
        booking_reference: Booking reference (optional)
        confirmation_number: Confirmation number (optional)
        order: Order within the travel plan (for sorting)
        created_at: Creation timestamp
    """

    id: UUID
    journal_id: int
    name: str
    check_in_date: date
    check_out_date: date
    order: int
    address: str | None = None
    booking_reference: str | None = None
    confirmation_number: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate travel accommodation properties."""
        self._validate_journal_id()
        self._validate_name()
        self._validate_dates()
        self._validate_optional_fields()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise TravelAccommodationValidationError(
                "journal_id", JOURNAL_ID_VALIDATION_MSG
            )

    def _validate_name(self) -> None:
        """Validate name is provided and within length limit."""
        if not self.name or not self.name.strip():
            raise TravelAccommodationValidationError("name", "Accommodation name is required")

        if len(self.name) > MAX_ACCOMMODATION_NAME_LENGTH:
            raise TravelAccommodationValidationError(
                "name",
                f"Accommodation name cannot exceed {MAX_ACCOMMODATION_NAME_LENGTH} characters",
            )

    def _validate_dates(self) -> None:
        """Validate check-in and check-out dates."""
        if self.check_in_date >= self.check_out_date:
            raise TravelAccommodationValidationError(
                "check_out_date", "Check-out date must be after check-in date"
            )

    def _validate_optional_fields(self) -> None:
        """Validate optional fields are within length limits."""
        if (
            self.booking_reference
            and len(self.booking_reference) > MAX_BOOKING_REFERENCE_LENGTH
        ):
            raise TravelAccommodationValidationError(
                "booking_reference",
                f"Booking reference cannot exceed {MAX_BOOKING_REFERENCE_LENGTH} characters",
            )

        if (
            self.confirmation_number
            and len(self.confirmation_number) > MAX_CONFIRMATION_NUMBER_LENGTH
        ):
            raise TravelAccommodationValidationError(
                "confirmation_number",
                f"Confirmation number cannot exceed {MAX_CONFIRMATION_NUMBER_LENGTH} characters",
            )


@dataclass
class TravelTransportation:
    """
    TravelTransportation entity for individual transportation within a TRAVEL type journal.

    Represents transportation information stored in journal_travel_transportation table.
    Transportation items are ordered within a travel journal using the order field.

    Attributes:
        id: Unique identifier for the transportation (UUID)
        journal_id: Foreign key to the journal
        type: Transportation type (required, e.g., "car_rental", "train", "bus")
        details: Transportation details (required)
        booking_reference: Booking reference (optional)
        order: Order within the travel plan (for sorting)
        created_at: Creation timestamp
    """

    id: UUID
    journal_id: int
    type: str
    details: str
    order: int
    booking_reference: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate travel transportation properties."""
        self._validate_journal_id()
        self._validate_type()
        self._validate_details()
        self._validate_optional_fields()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise TravelTransportationValidationError(
                "journal_id", JOURNAL_ID_VALIDATION_MSG
            )

    def _validate_type(self) -> None:
        """Validate type is provided and within length limit."""
        if not self.type or not self.type.strip():
            raise TravelTransportationValidationError("type", "Transportation type is required")

        if len(self.type) > MAX_TRANSPORTATION_TYPE_LENGTH:
            raise TravelTransportationValidationError(
                "type",
                f"Transportation type cannot exceed {MAX_TRANSPORTATION_TYPE_LENGTH} characters",
            )

    def _validate_details(self) -> None:
        """Validate details are provided."""
        if not self.details or not self.details.strip():
            raise TravelTransportationValidationError("details", "Transportation details are required")

    def _validate_optional_fields(self) -> None:
        """Validate optional fields are within length limits."""
        if (
            self.booking_reference
            and len(self.booking_reference) > MAX_BOOKING_REFERENCE_LENGTH
        ):
            raise TravelTransportationValidationError(
                "booking_reference",
                f"Booking reference cannot exceed {MAX_BOOKING_REFERENCE_LENGTH} characters",
            )


@dataclass
class TravelData:
    """
    TravelData entity for TRAVEL type journals.

    This entity represents additional data for journals that have the TRAVEL type.
    A journal is considered to have the TRAVEL type if a row exists in
    journal_travel_data for that journal_id.

    Travel data contains flights, accommodations, and transportation components.

    Attributes:
        journal_id: Foreign key to the journal (primary key in DB)
        flights: List of travel flights (loaded separately)
        accommodations: List of travel accommodations (loaded separately)
        transportation: List of travel transportation (loaded separately)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    journal_id: int
    flights: list[TravelFlight] = field(default_factory=list)
    accommodations: list[TravelAccommodation] = field(default_factory=list)
    transportation: list[TravelTransportation] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate travel data properties."""
        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        if self.journal_id <= 0:
            raise TravelDataValidationError(
                "journal_id", JOURNAL_ID_VALIDATION_MSG
            )
