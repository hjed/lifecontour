"""Unit tests for SummaryGenerator — orchestrator for AI summary generation."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import ContactSummary, SummaryStatus

from app.core.contacts.services.summary_generation_service import (
    SummaryGenerator,
    SummaryInput,
)


def _make_input(**overrides: Any) -> SummaryInput:
    """Create a SummaryInput with sensible defaults."""
    defaults: dict[str, Any] = {
        "contact_id": 1,
        "contact_name": "John Doe",
        "company": "Acme",
        "job_title": "Engineer",
        "recent_notes": ["Met for coffee"],
        "recent_journals": [
            {"title": "Lunch", "content": "Discussed work", "date": "2026-04-01"}
        ],
        "relationships": ["Friend: Jane"],
        "recent_history": ["Changed company"],
        "important_dates": ["Birthday: March 15"],
        "previous_summary": None,
        "activity_stats": [],
    }
    defaults.update(overrides)
    return SummaryInput(**defaults)


def _make_generator(
    assembler_result: SummaryInput | None = None,
    low_activity: bool = False,
    existing_summary: ContactSummary | None = None,
    gemini_response: str | None = None,
) -> SummaryGenerator:
    """Create a SummaryGenerator with mock dependencies."""
    input_assembler = AsyncMock()
    input_assembler.assemble = AsyncMock(return_value=assembler_result or _make_input())

    activity_checker = MagicMock()
    activity_checker.should_auto_disable = MagicMock(return_value=low_activity)

    prompt_builder = MagicMock()
    prompt_builder.build = MagicMock(return_value="Mock prompt text")

    summary_repo = AsyncMock()
    summary_repo.find_by_contact_id = AsyncMock(return_value=existing_summary)
    summary_repo.upsert = AsyncMock(side_effect=lambda s: s)
    summary_repo.update_status = AsyncMock(
        side_effect=lambda cid, status: ContactSummary(
            contact_id=cid, status=SummaryStatus(status)
        )
    )

    # Default valid Gemini response
    if gemini_response is None:
        gemini_response = json.dumps(
            {
                "summary_text": "John is a trusted colleague at Acme.",
                "follow_up_suggestions": [
                    "Schedule a catch-up",
                    "Ask about project X",
                ],
            }
        )

    return SummaryGenerator(
        input_assembler=input_assembler,
        activity_checker=activity_checker,
        prompt_builder=prompt_builder,
        summary_repo=summary_repo,
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        _gemini_response_override=gemini_response,
    )


@pytest.mark.unit
class TestSummaryGenerator:
    """Tests for SummaryGenerator orchestrator."""

    @pytest.mark.asyncio
    async def test_successful_generation_status_transitions(self):
        """Test status transitions: PENDING → GENERATING → GENERATED."""
        generator = _make_generator()

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "John is a trusted colleague at Acme."
        assert result.follow_up_suggestions == [
            "Schedule a catch-up",
            "Ask about project X",
        ]
        assert result.generated_at is not None

    @pytest.mark.asyncio
    async def test_sets_generating_status_before_ai_call(self):
        """Test that status is set to GENERATING before calling AI."""
        generator = _make_generator()
        await generator.generate(contact_id=1)

        # Verify update_status was called with GENERATING
        generator._summary_repo.update_status.assert_any_call(  # type: ignore[attr-defined]
            1, SummaryStatus.GENERATING.value
        )

    @pytest.mark.asyncio
    async def test_failed_generation_sets_failed_status(self):
        """Test that AI failure sets status to FAILED."""
        generator = _make_generator(gemini_response="INVALID_NOT_JSON")

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.FAILED

    @pytest.mark.asyncio
    async def test_low_activity_auto_disables(self):
        """Test that low-activity contacts are auto-disabled."""
        generator = _make_generator(low_activity=True)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        assert result.is_disabled is True

    @pytest.mark.asyncio
    async def test_disabled_contact_skipped(self):
        """Test that already disabled contacts (non-override) are skipped."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            is_user_override=False,
        )
        generator = _make_generator(existing_summary=existing)

        result = await generator.generate(contact_id=1)

        # Should return the existing disabled summary without attempting generation
        assert result is not None
        assert result.status == SummaryStatus.DISABLED

    @pytest.mark.asyncio
    async def test_user_override_respects_override(self):
        """Test that user override prevents auto-disable even with low activity."""
        existing = ContactSummary(
            contact_id=1,
            is_user_override=True,
            status=SummaryStatus.GENERATED,
        )
        generator = _make_generator(existing_summary=existing, low_activity=False)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_contact_not_found_returns_none(self):
        """Test that generating for non-existent contact returns None."""
        generator = _make_generator(assembler_result=None)
        # Override: make assembler return None
        generator._input_assembler.assemble = AsyncMock(return_value=None)  # type: ignore[method-assign]

        result = await generator.generate(contact_id=999)

        assert result is None

    @pytest.mark.asyncio
    async def test_parses_valid_json_response(self):
        """Test correct parsing of valid AI JSON response."""
        response = json.dumps(
            {
                "summary_text": "A test summary",
                "follow_up_suggestions": ["Do this", "Do that"],
            }
        )
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.summary_text == "A test summary"
        assert result.follow_up_suggestions == ["Do this", "Do that"]

    @pytest.mark.asyncio
    async def test_handles_malformed_json_response(self):
        """Test that malformed JSON from AI results in FAILED status."""
        generator = _make_generator(gemini_response="Not valid JSON at all")

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.FAILED

    @pytest.mark.asyncio
    async def test_handles_partial_json_response(self):
        """Test JSON response missing follow_up_suggestions still works."""
        response = json.dumps({"summary_text": "A summary without suggestions"})
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.summary_text == "A summary without suggestions"
        assert result.follow_up_suggestions == []

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        """Test that generation is skipped when no API key is configured."""
        generator = _make_generator()
        generator._gemini_api_key = ""

        result = await generator.generate(contact_id=1)

        assert result is None

    @pytest.mark.asyncio
    async def test_contact_not_found_does_not_set_generating(self):
        """Test that GENERATING status is NOT set when contact doesn't exist."""
        generator = _make_generator()
        generator._input_assembler.assemble = AsyncMock(return_value=None)  # type: ignore[method-assign]

        await generator.generate(contact_id=999)

        # update_status should NOT have been called (no stale GENERATING row)
        generator._summary_repo.update_status.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_preserves_user_override_on_generation(self):
        """Test that user override fields are preserved after successful generation."""
        existing = ContactSummary(
            contact_id=1,
            is_user_override=True,
            user_override_text="User's custom text",
            status=SummaryStatus.GENERATED,
        )
        generator = _make_generator(existing_summary=existing)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        # User override flag should be preserved
        assert result.is_user_override is True

    @pytest.mark.asyncio
    async def test_non_list_suggestions_coerced_to_empty(self):
        """Test that non-list follow_up_suggestions from AI is coerced to empty list."""
        response = json.dumps(
            {
                "summary_text": "A summary",
                "follow_up_suggestions": "not a list",
            }
        )
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.follow_up_suggestions == []

    @pytest.mark.asyncio
    async def test_null_suggestions_coerced_to_empty(self):
        """Test that null follow_up_suggestions is coerced to empty list."""
        response = json.dumps(
            {
                "summary_text": "A summary",
                "follow_up_suggestions": None,
            }
        )
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.follow_up_suggestions == []

    @pytest.mark.asyncio
    async def test_empty_summary_text_fails(self):
        """Test that empty summary_text from AI results in FAILED status."""
        response = json.dumps(
            {
                "summary_text": "",
                "follow_up_suggestions": [],
            }
        )
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.FAILED

    @pytest.mark.asyncio
    async def test_null_summary_text_fails(self):
        """Test that null summary_text from AI results in FAILED status."""
        response = json.dumps(
            {
                "summary_text": None,
                "follow_up_suggestions": [],
            }
        )
        generator = _make_generator(gemini_response=response)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.FAILED
