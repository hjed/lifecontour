from sqlalchemy import Column, DateTime, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.sql import func

from app.infrastructure.database_metadata import metadata

dead_letter_events_table = Table(
    "dead_letter_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(100), nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("aggregate_id", Integer, nullable=False),
    Column("event_data", JSONB, nullable=False),
    Column("consumer_group", String(100), nullable=False),
    Column("delivery_count", Integer, nullable=False),
    Column("last_error", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint(
        "event_id", "consumer_group", name="uq_dead_letter_event_consumer"
    ),
)
