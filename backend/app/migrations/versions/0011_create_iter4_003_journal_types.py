"""Create ITER4-003 journal types tables (PLAN, TRAVEL, PHOTO_ALBUM)

Revision ID: 0011
Revises: 0010
Create Date: 2024-12-09 12:00:00.000000

This migration creates the supporting tables for ITER4-003 journal types:
- journal_photo_album_data: PHOTO_ALBUM type data (Immich album links)
- journal_plan_data: PLAN type data (event planning)
- journal_plan_documents: Plan document links with ordering
- journal_travel_data: TRAVEL type data (travel itineraries)
- journal_travel_flights: Travel flight information with ordering
- journal_travel_accommodations: Travel accommodation information with ordering
- journal_travel_transportation: Travel transportation information with ordering

Type detection: A journal has a type if a row exists in the corresponding
type table (e.g., PLAN type if journal_plan_data row exists).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Constants from journal domain
MAX_IMMICH_ALBUM_ID_LENGTH = 255
MAX_PLAN_DOCUMENT_URL_LENGTH = 2000
MAX_PLAN_DOCUMENT_TITLE_LENGTH = 500
MAX_FLIGHT_NUMBER_LENGTH = 20
MAX_AIRLINE_LENGTH = 100
MAX_AIRPORT_CODE_LENGTH = 10
MAX_BOOKING_REFERENCE_LENGTH = 100
MAX_SEAT_NUMBER_LENGTH = 20
MAX_CONFIRMATION_NUMBER_LENGTH = 100
MAX_ACCOMMODATION_NAME_LENGTH = 200
MAX_TRANSPORTATION_TYPE_LENGTH = 50

# Migration constants to reduce duplication
JOURNALS_TABLE_FK = "journals.id"
JOURNAL_FK_COMMENT = "FK to journals - PK ensures one-to-one relationship"
TRAVEL_DATA_FK = "journal_travel_data.journal_id"
TRAVEL_DATA_FK_COMMENT = "FK to journal_travel_data"
UUID_DEFAULT = "gen_random_uuid()"
NOW_DEFAULT = "now()"
BOOKING_REF_COMMENT = "Booking reference number"
TRAVEL_ORDER_COMMENT = "Order within the travel plan for sorting"


def upgrade() -> None:
    """Create ITER4-003 journal types tables."""

    # Create journal_photo_album_data table (PHOTO_ALBUM type)
    op.create_table(
        "journal_photo_album_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(JOURNALS_TABLE_FK, ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment=JOURNAL_FK_COMMENT,
        ),
        sa.Column(
            "immich_album_id",
            sa.VARCHAR(length=MAX_IMMICH_ALBUM_ID_LENGTH),
            nullable=False,
            comment="Immich album identifier for photo integration",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("journal_id"),
    )

    # Create journal_plan_data table (PLAN type)
    op.create_table(
        "journal_plan_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(JOURNALS_TABLE_FK, ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment=JOURNAL_FK_COMMENT,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("journal_id"),
    )

    # Create journal_plan_documents table
    op.create_table(
        "journal_plan_documents",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text(UUID_DEFAULT),
            primary_key=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey("journal_plan_data.journal_id", ondelete="CASCADE"),
            nullable=False,
            comment="FK to journal_plan_data",
        ),
        sa.Column(
            "url",
            sa.VARCHAR(length=MAX_PLAN_DOCUMENT_URL_LENGTH),
            nullable=False,
            comment="Document URL",
        ),
        sa.Column(
            "title",
            sa.VARCHAR(length=MAX_PLAN_DOCUMENT_TITLE_LENGTH),
            nullable=False,
            comment="Document title",
        ),
        sa.Column(
            "description",
            sa.TEXT(),
            nullable=True,
            comment="Optional document description",
        ),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=False,
            comment="Order within the plan for sorting",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index for plan documents
    op.create_index(
        "idx_journal_plan_documents_journal_id_order",
        "journal_plan_documents",
        ["journal_id", "order"],
    )

    # Create journal_travel_data table (TRAVEL type)
    op.create_table(
        "journal_travel_data",
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(JOURNALS_TABLE_FK, ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
            comment=JOURNAL_FK_COMMENT,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("journal_id"),
    )

    # Create journal_travel_flights table
    op.create_table(
        "journal_travel_flights",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text(UUID_DEFAULT),
            primary_key=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(TRAVEL_DATA_FK, ondelete="CASCADE"),
            nullable=False,
            comment=TRAVEL_DATA_FK_COMMENT,
        ),
        sa.Column(
            "flight_number",
            sa.VARCHAR(length=MAX_FLIGHT_NUMBER_LENGTH),
            nullable=False,
            comment="Flight number (e.g., QF123)",
        ),
        sa.Column(
            "airline",
            sa.VARCHAR(length=MAX_AIRLINE_LENGTH),
            nullable=True,
            comment="Airline name",
        ),
        sa.Column(
            "departure_airport",
            sa.VARCHAR(length=MAX_AIRPORT_CODE_LENGTH),
            nullable=False,
            comment="Departure airport code",
        ),
        sa.Column(
            "arrival_airport",
            sa.VARCHAR(length=MAX_AIRPORT_CODE_LENGTH),
            nullable=False,
            comment="Arrival airport code",
        ),
        sa.Column(
            "departure_time",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Departure timestamp",
        ),
        sa.Column(
            "arrival_time",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Arrival timestamp",
        ),
        sa.Column(
            "booking_reference",
            sa.VARCHAR(length=MAX_BOOKING_REFERENCE_LENGTH),
            nullable=True,
            comment=BOOKING_REF_COMMENT,
        ),
        sa.Column(
            "seat_number",
            sa.VARCHAR(length=MAX_SEAT_NUMBER_LENGTH),
            nullable=True,
            comment="Seat number",
        ),
        sa.Column(
            "confirmation_number",
            sa.VARCHAR(length=MAX_CONFIRMATION_NUMBER_LENGTH),
            nullable=True,
            comment="Confirmation number",
        ),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=False,
            comment=TRAVEL_ORDER_COMMENT,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Check constraint for valid flight times
        sa.CheckConstraint(
            "departure_time < arrival_time",
            name="ck_journal_travel_flights_valid_times",
        ),
    )

    # Index for travel flights
    op.create_index(
        "idx_journal_travel_flights_journal_id_order",
        "journal_travel_flights",
        ["journal_id", "order"],
    )

    # Create journal_travel_accommodations table
    op.create_table(
        "journal_travel_accommodations",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text(UUID_DEFAULT),
            primary_key=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(TRAVEL_DATA_FK, ondelete="CASCADE"),
            nullable=False,
            comment=TRAVEL_DATA_FK_COMMENT,
        ),
        sa.Column(
            "name",
            sa.VARCHAR(length=MAX_ACCOMMODATION_NAME_LENGTH),
            nullable=False,
            comment="Accommodation name",
        ),
        sa.Column(
            "address",
            sa.TEXT(),
            nullable=True,
            comment="Accommodation address",
        ),
        sa.Column(
            "check_in_date",
            sa.Date(),
            nullable=False,
            comment="Check-in date",
        ),
        sa.Column(
            "check_out_date",
            sa.Date(),
            nullable=False,
            comment="Check-out date",
        ),
        sa.Column(
            "booking_reference",
            sa.VARCHAR(length=MAX_BOOKING_REFERENCE_LENGTH),
            nullable=True,
            comment=BOOKING_REF_COMMENT,
        ),
        sa.Column(
            "confirmation_number",
            sa.VARCHAR(length=MAX_CONFIRMATION_NUMBER_LENGTH),
            nullable=True,
            comment="Confirmation number",
        ),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=False,
            comment=TRAVEL_ORDER_COMMENT,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Check constraint for valid dates
        sa.CheckConstraint(
            "check_in_date < check_out_date",
            name="ck_journal_travel_accommodations_valid_dates",
        ),
    )

    # Index for travel accommodations
    op.create_index(
        "idx_journal_travel_accommodations_journal_id_order",
        "journal_travel_accommodations",
        ["journal_id", "order"],
    )

    # Create journal_travel_transportation table
    op.create_table(
        "journal_travel_transportation",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text(UUID_DEFAULT),
            primary_key=True,
        ),
        sa.Column(
            "journal_id",
            sa.Integer(),
            sa.ForeignKey(TRAVEL_DATA_FK, ondelete="CASCADE"),
            nullable=False,
            comment=TRAVEL_DATA_FK_COMMENT,
        ),
        sa.Column(
            "type",
            sa.VARCHAR(length=MAX_TRANSPORTATION_TYPE_LENGTH),
            nullable=False,
            comment="Transportation type (e.g., car_rental, train, bus)",
        ),
        sa.Column(
            "details",
            sa.TEXT(),
            nullable=False,
            comment="Transportation details",
        ),
        sa.Column(
            "booking_reference",
            sa.VARCHAR(length=MAX_BOOKING_REFERENCE_LENGTH),
            nullable=True,
            comment=BOOKING_REF_COMMENT,
        ),
        sa.Column(
            "order",
            sa.Integer(),
            nullable=False,
            comment=TRAVEL_ORDER_COMMENT,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text(NOW_DEFAULT),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Index for travel transportation
    op.create_index(
        "idx_journal_travel_transportation_journal_id_order",
        "journal_travel_transportation",
        ["journal_id", "order"],
    )


def downgrade() -> None:
    """Drop ITER4-003 journal types tables."""

    # Drop travel tables (in reverse order due to foreign keys)
    op.drop_index(
        "idx_journal_travel_transportation_journal_id_order",
        table_name="journal_travel_transportation",
    )
    op.drop_table("journal_travel_transportation")

    op.drop_index(
        "idx_journal_travel_accommodations_journal_id_order",
        table_name="journal_travel_accommodations",
    )
    op.drop_table("journal_travel_accommodations")

    op.drop_index(
        "idx_journal_travel_flights_journal_id_order",
        table_name="journal_travel_flights",
    )
    op.drop_table("journal_travel_flights")

    op.drop_table("journal_travel_data")

    # Drop plan tables (in reverse order due to foreign keys)
    op.drop_index(
        "idx_journal_plan_documents_journal_id_order",
        table_name="journal_plan_documents",
    )
    op.drop_table("journal_plan_documents")
    op.drop_table("journal_plan_data")

    # Drop photo album table
    op.drop_table("journal_photo_album_data")
