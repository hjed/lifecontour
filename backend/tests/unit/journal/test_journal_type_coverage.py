"""Completeness guard for every hand-maintained journal-type registry.

Type membership is represented by the presence of a type-data row, and each
layer keeps its own list of those rows: the SQL table map, the MCP read path,
the write service's presence/default-row helpers, and the MCP discovery
metadata. A type that is added to ``JournalType`` but missed from any one of
them is written but never read back (OUTDOOR_TRAINING was exactly that). These
tests fail the moment a ``JournalType`` is absent from a registry without an
explicit, reasoned exclusion here.
"""

import inspect
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import JournalType

from app.core.journal.adapters.sql import journal_repository
from app.core.journal.adapters.sql.logbook_export_repository import (
    SqlLogbookExportRepository,
)
from app.core.journal.services import journal_type_data_helpers as helpers
from app.core.journal.services import journal_type_data_reader as type_reader
from app.core.journal.services import journal_type_metadata as type_metadata
from app.core.journal.services.journal_enrichment_service import (
    JournalTypeDataRepositories,
)
from app.core.journal.services.journal_write_service import JournalWriteService
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from app.infrastructure.search.reindex_service import ReindexService
from app.mcp.domains.journals import schemas as mcp_schemas
from app.mcp.domains.journals.tools import _shared as mcp_tool_shared

# Types with no type-data table of their own, and why.
_NO_TABLE: dict[JournalType, str] = {
    JournalType.NOTE: "NOTE is the absence of any typed row",
    JournalType.PHOTO_ALBUM: (
        "integration-managed: detected via a sync_metadata row with "
        "integration_source='immich_album'"
    ),
}

_TABLE_BACKED = set(JournalType) - set(_NO_TABLE)


def test_repository_table_map_covers_every_table_backed_type() -> None:
    assert set(journal_repository.TYPE_TABLES) == _TABLE_BACKED


def test_repository_get_types_sql_names_every_table() -> None:
    """The type-detection query must LEFT JOIN every type-data table."""
    sql = journal_repository.GET_TYPES_SQL
    for journal_type, table in journal_repository.TYPE_TABLES.items():
        assert table in sql, f"{journal_type.value}: {table} missing from get_types"
        assert f"'{journal_type.name}'" in sql, (
            f"{journal_type.value}: name missing from get_types projection"
        )
    assert "immich_album" in sql


def test_mcp_read_path_reads_every_type() -> None:
    """Every type except NOTE must be readable by the MCP type_data reader."""
    assert set(type_reader.TYPE_DATA_READERS) == set(JournalType) - {JournalType.NOTE}


def test_mcp_repositories_expose_every_reader_repo() -> None:
    repo_fields = {
        f.name
        for f in mcp_tool_shared.JournalToolRepositories.__dataclass_fields__.values()
    }
    for journal_type, reader in type_reader.TYPE_DATA_READERS.items():
        assert reader.repo_attr in repo_fields, (
            f"{journal_type.value}: reader repo '{reader.repo_attr}' is not on "
            "_JournalToolRepositories"
        )


def test_mcp_discovery_describes_every_type() -> None:
    assert set(type_metadata.JOURNAL_TYPE_DESCRIPTIONS) == {t.name for t in JournalType}
    for name, description in type_metadata.JOURNAL_TYPE_DESCRIPTIONS.items():
        assert description.strip(), f"{name} has an empty description"


@pytest.mark.parametrize(
    "field_description",
    [
        mcp_schemas.JournalCreateRequest.model_fields["types"].description,
        mcp_schemas.JournalUpdateRequest.model_fields["types"].description,
    ],
)
def test_mcp_request_schemas_list_every_type(field_description: str | None) -> None:
    assert field_description is not None
    for journal_type in JournalType:
        assert journal_type.name in field_description, (
            f"{journal_type.name} missing from the 'types' field description"
        )


def _write_service() -> JournalWriteService:
    params = inspect.signature(JournalWriteService.__init__).parameters
    kwargs = {name: AsyncMock() for name in params if name != "self"}
    return JournalWriteService(**kwargs)


def test_write_service_presence_repos_cover_every_table_backed_type() -> None:
    covered = {jt for jt, _ in _write_service()._type_presence_repos()}
    assert covered == _TABLE_BACKED


@pytest.mark.parametrize(
    "helper", [helpers.create_type_specific_data, helpers.delete_type_specific_data]
)
def test_type_data_helpers_handle_every_table_backed_type(helper) -> None:
    """The default-row create/delete dispatchers must name every typed row.

    EVENT's row (journal_calendar_info) is created by the calendar path and
    deleted explicitly by the write service, so it is the one table-backed type
    the generic helpers legitimately omit.
    """
    source = inspect.getsource(helper)
    missing = {
        jt
        for jt in _TABLE_BACKED - {JournalType.EVENT}
        if f"JournalType.{jt.name}" not in source
    }
    assert not missing, f"{helper.__name__} does not handle {sorted(missing)}"


@pytest.mark.parametrize(
    ("owner", "method"),
    [
        (JournalIndexingService, "_fetch_complete_journal_data"),
        (ReindexService, "_fetch_journal_document"),
    ],
)
def test_search_indexers_take_types_from_the_repository(owner, method) -> None:
    """The search index must carry every type, not a hand-rolled subset.

    Both indexers used to know only five types, so fitness/activity journals
    were indexed as plain notes and a ``types`` filter never matched them.
    """
    source = inspect.getsource(getattr(owner, method))
    assert ".get_concrete_types(" in source
    assert "CASE WHEN" not in source


def test_logbook_export_uses_the_generated_batch_types_query() -> None:
    source = inspect.getsource(SqlLogbookExportRepository)
    assert "GET_TYPES_BATCH_SQL" in source
    assert "CASE WHEN" not in source


def test_enrichment_repositories_expose_every_reader_repo() -> None:
    """The core enrichment read finds each type's repository by ``repo_attr``."""
    repo_fields = {
        f.name for f in JournalTypeDataRepositories.__dataclass_fields__.values()
    }
    for journal_type, reader in type_reader.TYPE_DATA_READERS.items():
        assert reader.repo_attr in repo_fields, (
            f"{journal_type.value}: reader repo '{reader.repo_attr}' is not on "
            "JournalTypeDataRepositories"
        )
