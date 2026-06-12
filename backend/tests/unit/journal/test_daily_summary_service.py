"""Unit tests for DailySummaryService."""

import json
from datetime import date
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_service import DailySummaryService

# These unit tests mock the repository, so no real connection is needed: the
# @transactional decorator no-ops for a non-AsyncConnection (the value is never
# used to commit). cast keeps the typed signature happy without a real engine.
_NO_TXN = cast(AsyncConnection, None)


@pytest.fixture
def mock_input_assembler() -> AsyncMock:
    assembler = AsyncMock()
    assembler.assemble.return_value = DailySummaryInput(
        user_id="user123",
        summary_date=date(2026, 4, 27),
        journals=[],
        journal_count=3,
        event_count=1,
        contact_names=["Alice", "Bob"],
        mood_values=[7, 8],
    )
    return assembler


@pytest.fixture
def mock_eligibility_checker() -> MagicMock:
    checker = MagicMock()
    checker.is_eligible.return_value = True
    return checker


@pytest.fixture
def mock_prompt_builder() -> MagicMock:
    builder = MagicMock()
    builder.build.return_value = "test prompt"
    return builder


@pytest.fixture
def mock_summary_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_user_and_date.return_value = None
    repo.upsert.side_effect = lambda s: s  # Return what's passed in
    repo.update_status.return_value = None  # No existing row by default
    repo.invalidate_for_date.return_value = None
    return repo


@pytest.fixture
def service(
    mock_input_assembler: AsyncMock,
    mock_eligibility_checker: MagicMock,
    mock_prompt_builder: MagicMock,
    mock_summary_repo: AsyncMock,
) -> DailySummaryService:
    return DailySummaryService(
        input_assembler=mock_input_assembler,
        eligibility_checker=mock_eligibility_checker,
        prompt_builder=mock_prompt_builder,
        summary_repo=mock_summary_repo,
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-pro",
        _gemini_response_override=json.dumps(
            {"summary_text": "A productive day with meetings and exercise."}
        ),
    )


class TestDailySummaryServiceGeneration:
    """Test the get_or_generate pipeline."""

    @pytest.mark.asyncio
    async def test_generates_new_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
        mock_prompt_builder: MagicMock,
    ) -> None:
        """When no cached summary exists, generates a new one."""
        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "A productive day with meetings and exercise."
        assert result.journal_count == 3
        assert result.event_count == 1
        assert result.contact_count == 2  # Alice, Bob (deduplicated)
        assert result.mood_average == 7.5
        assert result.generated_at is not None
        mock_input_assembler.assemble.assert_called_once_with(
            "user123", date(2026, 4, 27), "UTC"
        )
        mock_prompt_builder.build.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_cached_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When a GENERATED summary exists, returns it without regenerating."""
        cached = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            summary_text="Cached summary.",
            status=SummaryStatus.GENERATED,
        )
        mock_summary_repo.find_by_user_and_date.return_value = cached

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is cached
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_generating_summary_without_retry(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is GENERATING, returns it without starting a new generation."""
        generating = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )
        mock_summary_repo.find_by_user_and_date.return_value = generating

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is generating
        mock_input_assembler.assemble.assert_not_called()

    @pytest.mark.asyncio
    async def test_regenerates_pending_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is PENDING, triggers regeneration."""
        pending = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.PENDING,
        )
        mock_summary_repo.find_by_user_and_date.return_value = pending
        # update_status returns the updated entity when the row exists
        mock_summary_repo.update_status.return_value = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        mock_input_assembler.assemble.assert_called_once()

    @pytest.mark.asyncio
    async def test_regenerates_failed_summary(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """When status is FAILED, triggers regeneration."""
        failed = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.FAILED,
        )
        mock_summary_repo.find_by_user_and_date.return_value = failed
        # update_status returns the updated entity when the row exists
        mock_summary_repo.update_status.return_value = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.GENERATING,
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        mock_input_assembler.assemble.assert_called_once()


class TestDailySummaryServiceEligibility:
    """Test eligibility checking."""

    @pytest.mark.asyncio
    async def test_ineligible_day_returns_disabled(
        self,
        service: DailySummaryService,
        mock_eligibility_checker: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """When the day is ineligible, returns a DISABLED summary."""
        mock_eligibility_checker.is_eligible.return_value = False

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        mock_summary_repo.upsert.assert_called_once()


class TestDailySummaryServiceFailure:
    """Test failure handling."""

    @pytest.mark.asyncio
    async def test_gemini_failure_returns_failed(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """When Gemini returns invalid JSON, the summary is set to FAILED."""
        # After upsert fallback, find_by_user_and_date is called to return the entity
        failed_entity = JournalDailySummary(
            user_id="user123",
            summary_date=date(2026, 4, 27),
            status=SummaryStatus.FAILED,
        )
        # First call: cache check returns None; second call: returns the upserted entity
        mock_summary_repo.find_by_user_and_date.side_effect = [None, failed_entity]

        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override="not valid json",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        # update_status returns None (no existing row), so upsert is used as fallback
        mock_summary_repo.update_status.assert_any_call(
            "user123", date(2026, 4, 27), "failed"
        )
        assert result is not None
        assert result.status == SummaryStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(
        self,
        mock_input_assembler: AsyncMock,
        mock_eligibility_checker: MagicMock,
        mock_prompt_builder: MagicMock,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """When no API key is configured, returns None."""
        service = DailySummaryService(
            input_assembler=mock_input_assembler,
            eligibility_checker=mock_eligibility_checker,
            prompt_builder=mock_prompt_builder,
            summary_repo=mock_summary_repo,
            gemini_api_key="",
            gemini_model="gemini-2.5-pro",
        )

        result = await service.get_or_generate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        assert result is None
        mock_input_assembler.assemble.assert_not_called()


class TestDailySummaryServiceRegenerate:
    """Test explicit regeneration."""

    @pytest.mark.asyncio
    async def test_regenerate_invalidates_then_generates(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
        mock_input_assembler: AsyncMock,
    ) -> None:
        """Regenerate invalidates cache then delegates to get_or_generate."""
        result = await service.regenerate(
            "user123", date(2026, 4, 27), transaction=_NO_TXN
        )

        mock_summary_repo.invalidate_for_date.assert_called_once_with(
            "user123", date(2026, 4, 27)
        )
        assert result is not None
        assert result.status == SummaryStatus.GENERATED


class TestDailySummaryServiceInvalidation:
    """Test cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_calls_repo(
        self,
        service: DailySummaryService,
        mock_summary_repo: AsyncMock,
    ) -> None:
        """Invalidate delegates to the repository."""
        await service.invalidate("user123", date(2026, 4, 27))

        mock_summary_repo.invalidate_for_date.assert_called_once_with(
            "user123", date(2026, 4, 27)
        )


class TestDailySummaryServiceParseResponse:
    """Test response parsing."""

    def test_parse_valid_json(self) -> None:
        """Valid JSON is parsed correctly."""
        raw = json.dumps({"summary_text": "A good day."})
        result = DailySummaryService._parse_response(raw)
        assert result["summary_text"] == "A good day."

    def test_parse_markdown_fenced_json(self) -> None:
        """JSON wrapped in markdown code fences is parsed."""
        raw = '```json\n{"summary_text": "A good day."}\n```'
        result = DailySummaryService._parse_response(raw)
        assert result["summary_text"] == "A good day."

    def test_parse_missing_summary_text(self) -> None:
        """Missing summary_text raises ValueError."""
        raw = json.dumps({"other_field": "value"})
        with pytest.raises(ValueError, match="summary_text"):
            DailySummaryService._parse_response(raw)

    def test_parse_empty_summary_text(self) -> None:
        """Empty summary_text raises ValueError."""
        raw = json.dumps({"summary_text": ""})
        with pytest.raises(ValueError, match="non-empty"):
            DailySummaryService._parse_response(raw)

    def test_parse_invalid_json(self) -> None:
        """Invalid JSON raises json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            DailySummaryService._parse_response("not json")


class TestDailySummaryServiceMoodAverage:
    """Test mood average computation."""

    def test_average_with_values(self) -> None:
        assert DailySummaryService._compute_mood_average([6, 8, 7]) == 7.0

    def test_average_with_single_value(self) -> None:
        assert DailySummaryService._compute_mood_average([5]) == 5.0

    def test_average_with_no_values(self) -> None:
        assert DailySummaryService._compute_mood_average([]) is None

    def test_average_rounding(self) -> None:
        assert DailySummaryService._compute_mood_average([7, 8]) == 7.5


class TestSanitizeSchema:
    """Test schema sanitization for google-genai bug.

    Tests the shared sanitize_schema function from app.mcp.shared.read_only_tools.
    """

    def test_sanitize_removes_boolean_additional_properties(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "additionalProperties": False,
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
        sanitize_schema(schema)
        assert "additionalProperties" not in schema
        assert schema["type"] == "object"
        assert "a" in schema["properties"]

    def test_sanitize_removes_boolean_items(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {"items": False, "type": "array"}
        sanitize_schema(schema)
        assert "items" not in schema
        assert schema["type"] == "array"

    def test_sanitize_recursively_removes_properties(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"deep": {"type": "array", "items": False}},
                }
            },
            "anyOf": [{"type": "object", "additionalProperties": False}],
        }
        sanitize_schema(schema)

        assert "additionalProperties" not in schema["properties"]["nested"]
        assert "items" not in schema["properties"]["nested"]["properties"]["deep"]
        assert "additionalProperties" not in schema["anyOf"][0]

    def test_sanitize_ignores_non_booleans(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        schema: dict[str, Any] = {
            "additionalProperties": {"type": "string"},
            "items": {"type": "integer"},
        }
        sanitize_schema(schema)
        assert schema["additionalProperties"] == {"type": "string"}
        assert schema["items"] == {"type": "integer"}

    def test_sanitize_ignores_non_dicts(self) -> None:
        from app.mcp.shared.read_only_tools import sanitize_schema

        # Should not raise any exceptions
        sanitize_schema("not a dict")  # type: ignore
        sanitize_schema(None)  # type: ignore
