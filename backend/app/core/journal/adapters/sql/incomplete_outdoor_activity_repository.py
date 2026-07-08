"""SQL implementation of the incomplete outdoor activities facts projection.

One query gathers every fact the incompleteness rules need: the user's outdoor
journals (anchored on ``journal_outdoor_activity_data``), each present subtype
row, and the participant / abseil-pitch counts. Every subtype table is keyed
1:1 on ``journal_id``, so the LEFT JOINs cannot fan out.

The subtype SELECT list is generated from ``SUBTYPE_FACTS_FIELDS`` and the
subtype dataclasses, so a model gaining a column flows into the projection
with no SQL edits (guarded by ``test_incomplete_projection_registry.py``).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from core_shared.models.journals import (
    SUBTYPE_FACTS_FIELDS,
    EventDateRange,
    JournalContactRelationshipType,
    OutdoorActivityFacts,
)
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import IncompleteOutdoorActivityRepository

# Facts attribute → table, for every registry subtype. Kept next to the
# generated SQL because table names are not uniformly derivable from the
# attribute (CROSS_COUNTRY_SKIING persists to ``journal_skiing_data``).
_SUBTYPE_TABLES: dict[str, str] = {
    "bushwalking_data": "journal_bushwalking_data",
    "abseiling_data": "journal_abseiling_data",
    "canyoning_data": "journal_canyoning_data",
    "climbing_data": "journal_climbing_data",
    "kayaking_data": "journal_kayaking_data",
    "cross_country_skiing_data": "journal_skiing_data",
    "caving_data": "journal_caving_data",
    "canoeing_data": "journal_canoeing_data",
    "snorkelling_data": "journal_snorkelling_data",
    "diving_data": "journal_diving_data",
    "downhill_skiing_data": "journal_downhill_skiing_data",
}

# Dataclass-managed timestamps are not needed by the rules.
_TIMESTAMP_FIELDS = frozenset({"created_at", "updated_at"})


def _select_fields(model: type[Any]) -> tuple[str, ...]:
    """The model's persisted fields (keys + attributes, no timestamps)."""
    return tuple(
        f.name for f in dataclasses.fields(model) if f.name not in _TIMESTAMP_FIELDS
    )


# ``alias__field`` output columns for every subtype, e.g.
# ``canyoning_data__french_grade``. Guarded to cover every fillable field.
SUBTYPE_SELECT_COLUMNS: tuple[str, ...] = tuple(
    f"{facts_attr}__{field_name}"
    for facts_attr, model in SUBTYPE_FACTS_FIELDS.values()
    for field_name in _select_fields(model)
)

_SUBTYPE_SELECT_SQL = ",\n    ".join(
    f"{facts_attr}.{field_name} AS {facts_attr}__{field_name}"
    for facts_attr, model in SUBTYPE_FACTS_FIELDS.values()
    for field_name in _select_fields(model)
)

_SUBTYPE_JOIN_SQL = "\n".join(
    f"LEFT JOIN {_SUBTYPE_TABLES[facts_attr]} {facts_attr}"
    f" ON {facts_attr}.journal_id = j.id"
    for facts_attr, _model in SUBTYPE_FACTS_FIELDS.values()
)

_FACTS_QUERY = text(
    f"""
    SELECT
        j.id AS journal_id,
        j.title AS title,
        j.event_date_range_start AS event_start,
        j.event_date_range_end AS event_end,
        {_SUBTYPE_SELECT_SQL},
        (outdoor_training.journal_id IS NOT NULL) AS has_outdoor_training,
        COALESCE(participants.participant_count, 0) AS participant_count,
        COALESCE(pitches.pitch_count, 0) AS abseil_pitch_count
    FROM journals j
    JOIN journal_outdoor_activity_data outdoor_activity
        ON outdoor_activity.journal_id = j.id
    {_SUBTYPE_JOIN_SQL}
    LEFT JOIN journal_outdoor_training_data outdoor_training
        ON outdoor_training.journal_id = j.id
    LEFT JOIN (
        SELECT journal_id, COUNT(*) AS participant_count
        FROM journal_contact_relationships
        WHERE relationship_type = :participant_type
        GROUP BY journal_id
    ) participants ON participants.journal_id = j.id
    LEFT JOIN (
        SELECT journal_id, COUNT(*) AS pitch_count
        FROM abseil_pitches
        GROUP BY journal_id
    ) pitches ON pitches.journal_id = j.id
    WHERE j.user_id = :user_id
    """
)


class SqlIncompleteOutdoorActivityRepository(IncompleteOutdoorActivityRepository):
    """Single-query facts projection over the user's outdoor journals."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def list_outdoor_activity_facts(
        self, user_id: str
    ) -> list[OutdoorActivityFacts]:
        """Fetch the facts for every outdoor journal owned by ``user_id``."""
        result = await self.connection.execute(
            _FACTS_QUERY,
            {
                "user_id": user_id,
                "participant_type": JournalContactRelationshipType.PARTICIPANT.value,
            },
        )
        return [self._row_to_facts(row_mapping) for row_mapping in result.mappings()]

    @staticmethod
    def _row_to_facts(row: RowMapping) -> OutdoorActivityFacts:
        subtype_data: dict[str, Any] = {}
        for facts_attr, model in SUBTYPE_FACTS_FIELDS.values():
            if row[f"{facts_attr}__journal_id"] is None:
                continue
            subtype_data[facts_attr] = model(
                **{
                    field_name: row[f"{facts_attr}__{field_name}"]
                    for field_name in _select_fields(model)
                }
            )
        return OutdoorActivityFacts(
            journal_id=int(row["journal_id"]),
            title=str(row["title"]),
            event_date_range=EventDateRange(
                start=row["event_start"], end=row["event_end"]
            ),
            has_outdoor_training=bool(row["has_outdoor_training"]),
            participant_count=int(row["participant_count"]),
            abseil_pitch_count=int(row["abseil_pitch_count"]),
            **subtype_data,
        )
