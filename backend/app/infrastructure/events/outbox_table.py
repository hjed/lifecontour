"""
Outbox table definition for transactional outbox pattern.

Stores domain events in the same transaction as business data changes
to ensure reliable event publishing to external systems like MeiliSearch.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Table, Text

from app.infrastructure.database_metadata import metadata

# Outbox events table for transactional outbox pattern
outbox_events_table = Table(
    "outbox_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(255), unique=True, nullable=False, index=True),
    Column("event_type", String(100), nullable=False, index=True),
    Column("aggregate_id", Integer, nullable=False, index=True),
    Column("event_data", Text, nullable=False),  # JSON as text
    Column("occurred_at", DateTime, nullable=False, default=datetime.utcnow),
    Column("processed_at", DateTime, nullable=True, index=True),
    Column("relayed_at", DateTime, nullable=True, index=True),
    Column("retry_count", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)
