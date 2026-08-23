"""Unit coverage for the MeiliSearch-backed journal search helpers."""

from unittest.mock import MagicMock

import pytest
from meilisearch.errors import MeilisearchError

from app.core.journal.services.journal_search_service import (
    hit_from_document as _search_hit_to_result,
)
from app.core.journal.services.journal_search_service import (
    search_journals_text as _meili_search_journals,
)
from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.search.meilisearch_client import (
    JOURNAL_INDEX_SETTINGS,
    JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES,
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
    assert result.start.year == 2025


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


def test_empty_id_set_short_circuits_without_calling_meili() -> None:
    """`id IN []` is a MeiliSearch error, and an empty window is not an outage."""
    service = MagicMock()

    assert _meili_search_journals(
        service, query="Zion", user_id="u1", limit=5, journal_ids=set()
    ) == ([], 0, 0)
    service.search_journals.assert_not_called()
