"""Guard: the incomplete-review projection self-maintains against the models.

The projection derives rule 1 ("no attributes set") and its fieldless-subtype
exemption from the subtype dataclasses via ``fillable_fields``. These checks
keep the three moving parts aligned so a subtype model gaining a column flows
into the projection without manual edits:

1. every registry entry maps to a real ``OutdoorActivityFacts`` field, and
2. the SQL adapter's generated SELECT list covers every fillable field of
   every registry model (plus the abseiling ``template_id`` rule 2 reads).

Registry completeness against ``OutdoorActivitySubtype`` itself is pinned in
``core_shared/tests/unit/models/journals/test_incomplete_outdoor_activity.py``,
next to the registry.
"""

import dataclasses

import pytest
from core_shared.models.journals import (
    SUBTYPE_FACTS_FIELDS,
    OutdoorActivityFacts,
    fillable_fields,
)

from app.core.journal.adapters.sql.incomplete_outdoor_activity_repository import (
    SUBTYPE_SELECT_COLUMNS,
)

_FACTS_FIELDS = {f.name: f for f in dataclasses.fields(OutdoorActivityFacts)}


class TestIncompleteProjectionRegistry:
    @pytest.mark.parametrize(
        ("facts_attr", "model"),
        list(SUBTYPE_FACTS_FIELDS.values()),
        ids=[str(subtype) for subtype in SUBTYPE_FACTS_FIELDS],
    )
    def test_registry_attrs_match_facts_dataclass_fields(
        self, facts_attr: str, model: type
    ) -> None:
        assert facts_attr in _FACTS_FIELDS, (
            f"SUBTYPE_FACTS_FIELDS maps to {facts_attr!r}, which is not a field "
            "of OutdoorActivityFacts"
        )
        assert model.__name__ in str(_FACTS_FIELDS[facts_attr].type), (
            f"OutdoorActivityFacts.{facts_attr} is not typed as {model.__name__}"
        )

    def test_repo_select_list_covers_every_fillable_field(self) -> None:
        for facts_attr, model in SUBTYPE_FACTS_FIELDS.values():
            expected = {f"{facts_attr}__journal_id"} | {
                f"{facts_attr}__{f.name}" for f in fillable_fields(model)
            }
            missing = expected - set(SUBTYPE_SELECT_COLUMNS)
            assert not missing, (
                f"SQL adapter SELECT list is missing columns for {model.__name__}: "
                f"{sorted(missing)}"
            )

    def test_repo_select_list_includes_abseiling_template_id(self) -> None:
        assert "abseiling_data__template_id" in SUBTYPE_SELECT_COLUMNS
