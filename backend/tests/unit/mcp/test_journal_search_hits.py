"""Unit coverage for the MeiliSearch-backed journal search helpers."""

from unittest.mock import MagicMock

import pytest
from meilisearch.errors import MeilisearchError

from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.search.meilisearch_client import (
    JOURNAL_INDEX_SETTINGS,
    JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES,
)
from app.mcp.domains.journals.tools import (
    _meili_search_journals,
    _search_hit_to_result,
)


def test_journal_index_can_filter_by_id_for_source_intersection() -> None:
    assert "id" in JOURNAL_INDEX_SETTINGS["filterableAttributes"]
    assert set(JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES) <= set(
        JOURNAL_INDEX_SETTINGS["filterableAttributes"]
    )


def test_hit_is_rendered_with_lowercase_types_and_highlights() -> None:
    result = _search_hit_to_result(
        {
            "id": 7,
            "title": "Echo Canyon — Zion",
            "content": "x" * 250,
            "event_date_range_start": "2025-10-13T15:05:11+00:00",
            "event_date_range_end": "2025-10-13T21:33:19+00:00",
            "types": ["FITNESS", "CANYONING"],
            "_formatted": {"title": "Echo Canyon — <mark>Zion</mark>", "content": "x"},
        }
    )
    assert result.id == 7
    assert result.types == ["fitness", "canyoning"]
    assert result.content_excerpt.endswith("...")
    assert result.highlighted == {"title": "Echo Canyon — <mark>Zion</mark>"}
    assert result.event_date_range.start.year == 2025


def test_filters_carry_user_types_and_source_ids() -> None:
    service = MagicMock()
    service.search_journals.return_value = {
        "hits": [],
        "estimated_total_hits": 0,
        "processing_time_ms": 3,
    }

    results, total, ms = _meili_search_journals(
        service,
        query="Zion canyoning",
        user_id="u1",
        limit=5,
        type_filters=["canyoning"],
        journal_ids={9, 3},
    )

    assert (results, total, ms) == ([], 0, 3)
    service.search_journals.assert_called_once_with(
        query="Zion canyoning",
        filters={"user_id": "u1", "types": ["CANYONING"], "id": [3, 9]},
        limit=5,
        offset=0,
    )


def test_meilisearch_error_becomes_search_unavailable() -> None:
    service = MagicMock()
    service.search_journals.side_effect = MeilisearchError("down")

    with pytest.raises(SearchServiceUnavailableError):
        _meili_search_journals(service, query="x", user_id="u1", limit=5)
