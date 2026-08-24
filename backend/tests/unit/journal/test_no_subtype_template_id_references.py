"""Guard: no code path references the retired per-subtype ``template_id`` columns.

ITER16-001 Phase 5 consolidates the template reference onto
``journal_abseiling_data.template_id`` and drops the per-subtype
``template_id`` columns from ``journal_canyoning_data`` /
``journal_climbing_data`` / ``journal_caving_data``.

This is the automated form of the "grep gate" precedent used in prior
drop-column migrations (e.g. 0093). Three complementary checks:

1. The subtype domain entities (``CanyoningData`` / ``CavingData`` /
   ``ClimbingData``) no longer declare a ``template_id`` field. Every read path
   (``_row_to_entity``) and write path (``data.template_id``) flows through these
   entities, so this is the keystone runtime guarantee.
2. A source scan of the subtype repository SQL and the MCP tool builders/updaters
   confirms no lingering ``template_id`` reference that would break at runtime once
   the columns are gone.
3. The type metadata behind ``list_journal_types`` no longer advertises the field
   on a subtype — a retired field there is worse than useless, since a caller who
   follows it has their value silently discarded.

The consolidated ``AbseilingData.template_id`` reference is intentionally allowed.
"""

import dataclasses
from pathlib import Path

import pytest
from core_shared.models.journals import (
    AbseilingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    JournalType,
)
from core_shared.models.journals.type_data_schemas import TYPE_DATA_MODELS

_THIS = Path(__file__).resolve()
_BACKEND_ROOT = _THIS.parents[3]  # …/backend

_SUBTYPE_REPO_FILES = (
    _BACKEND_ROOT / "app/core/journal/adapters/sql/canyoning_data_repository.py",
    _BACKEND_ROOT / "app/core/journal/adapters/sql/climbing_data_repository.py",
    _BACKEND_ROOT / "app/core/journal/adapters/sql/caving_data_repository.py",
)

_MCP_TOOLS_FILE = _BACKEND_ROOT / "app/mcp/domains/journals/tools.py"


def _field_names(entity: type) -> set[str]:
    return {f.name for f in dataclasses.fields(entity)}


class TestNoSubtypeTemplateIdReferences:
    """Static + reflective guard over the retired columns."""

    @pytest.mark.parametrize("entity", [CanyoningData, CavingData, ClimbingData])
    def test_subtype_entity_has_no_template_id(self, entity: type) -> None:
        assert "template_id" not in _field_names(entity), (
            f"{entity.__name__} still declares a template_id field; the reference "
            "is consolidated onto AbseilingData."
        )

    def test_abseiling_entity_keeps_template_id(self) -> None:
        # The consolidated reference must remain.
        assert "template_id" in _field_names(AbseilingData)

    def test_subtype_repositories_have_no_template_id_sql(self) -> None:
        offenders: list[str] = []
        for path in _SUBTYPE_REPO_FILES:
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if "template_id" in line:
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        assert not offenders, (
            "Subtype repository still references template_id:\n" + "\n".join(offenders)
        )

    def test_type_metadata_advertises_template_id_only_for_abseiling(self) -> None:
        """list_journal_types must not offer a field the write path discards.

        The metadata is what an MCP client reads before composing ``type_data``;
        a retired ``template_id`` on a subtype sends the caller's value into a
        column that no longer exists, and it is dropped without a word.
        """
        offenders = [
            journal_type.name
            for journal_type, model in TYPE_DATA_MODELS.items()
            if "template_id" in model.model_fields
            and journal_type is not JournalType.ABSEILING_TRIP
        ]
        assert not offenders, (
            "Type metadata still advertises a subtype template_id for: "
            + ", ".join(offenders)
        )
        assert (
            "template_id" in TYPE_DATA_MODELS[JournalType.ABSEILING_TRIP].model_fields
        )

    def test_mcp_tools_have_no_subtype_template_id(self) -> None:
        text = _MCP_TOOLS_FILE.read_text(encoding="utf-8")
        forbidden = (
            "caving_data.template_id",
            "climbing_data.template_id",
            "canyoning_data.template_id",
        )
        offenders = [
            f"{lineno}: {line.strip()}"
            for lineno, line in enumerate(text.splitlines(), start=1)
            if any(needle in line for needle in forbidden)
        ]
        assert not offenders, (
            "MCP tools still reference a subtype template_id:\n" + "\n".join(offenders)
        )
