"""Unit tests for SummaryGenerator — orchestrator for AI summary generation."""

import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import (
    ContactSummary,
    SummaryDisabledReason,
    SummaryStatus,
)

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
        "future_journals": [],
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
    summary_repo.upsert_from_generation = AsyncMock(side_effect=lambda s: s)
    summary_repo.update_status_unless_user_disabled = AsyncMock(
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

    # ITER12-003 Phase 2: summary history is derived from the ContactSummaryUpdated
    # event published here, so wire a mock publisher (no real connection → the
    # atomicity assertion short-circuits and the event records via the projection).
    event_publisher = AsyncMock()

    return SummaryGenerator(
        input_assembler=input_assembler,
        activity_checker=activity_checker,
        prompt_builder=prompt_builder,
        summary_repo=summary_repo,
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        _gemini_response_override=gemini_response,
        event_publisher=event_publisher,
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

        # Verify a ContactSummaryUpdated event was published (history is projected
        # from it). ITER12-003 Phase 2.
        assert generator._event_publisher is not None
        publish_mock = cast(AsyncMock, generator._event_publisher.publish)
        publish_mock.assert_awaited_once()
        event = publish_mock.await_args_list[0].args[0]
        assert event.event_type == "ContactSummaryUpdated"
        assert event.event_data["contact_id"] == 1
        assert "summary_text" in event.event_data["changed_fields"]

    @pytest.mark.asyncio
    async def test_writes_only_through_user_disable_guards(self):
        """No row lock is held across the AI call; every write is guarded so a
        user disable committed after the read is never overwritten."""
        generator = _make_generator()
        repo = cast(Any, generator._summary_repo)

        await generator.generate(contact_id=1)

        repo.find_by_contact_id.assert_awaited_once_with(1)
        repo.update_status_unless_user_disabled.assert_awaited_once_with(
            1, SummaryStatus.GENERATING.value
        )
        repo.upsert_from_generation.assert_awaited_once()
        repo.update_status.assert_not_awaited()
        repo.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_disable_before_generating_stops_generation(self):
        """A disable committed before GENERATING is written stops the run."""
        enabled = ContactSummary(contact_id=1, status=SummaryStatus.PENDING)
        user_disabled = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        generator = _make_generator(existing_summary=enabled)
        repo = cast(Any, generator._summary_repo)
        repo.find_by_contact_id = AsyncMock(side_effect=[enabled, user_disabled])
        repo.update_status_unless_user_disabled = AsyncMock(return_value=None)

        result = await generator.generate(contact_id=1)

        assert result is user_disabled
        cast(MagicMock, generator._prompt_builder.build).assert_not_called()
        repo.upsert_from_generation.assert_not_awaited()
        assert generator._event_publisher is not None
        cast(AsyncMock, generator._event_publisher.publish).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_disable_on_a_new_row_stops_generation(self):
        """With no row at the read, a disable inserted before GENERATING still
        stops the run before any AI call."""
        user_disabled = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        generator = _make_generator(existing_summary=None)
        repo = cast(Any, generator._summary_repo)
        repo.find_by_contact_id = AsyncMock(side_effect=[None, user_disabled])
        repo.update_status_unless_user_disabled = AsyncMock(return_value=None)

        result = await generator.generate(contact_id=1)

        assert result is user_disabled
        cast(MagicMock, generator._prompt_builder.build).assert_not_called()
        repo.upsert_from_generation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_row_still_generates(self):
        """No row at the read and none at GENERATING is a first summary, not a
        disable: generation carries on and creates the row."""
        generator = _make_generator(existing_summary=None)
        repo = cast(Any, generator._summary_repo)
        repo.find_by_contact_id = AsyncMock(side_effect=[None, None])
        repo.update_status_unless_user_disabled = AsyncMock(return_value=None)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        cast(MagicMock, generator._prompt_builder.build).assert_called_once()
        repo.upsert_from_generation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_user_disable_during_ai_call_keeps_their_choice(self):
        """A disable committed while the AI call runs is kept, with no history."""
        enabled = ContactSummary(contact_id=1, status=SummaryStatus.PENDING)
        user_disabled = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        generator = _make_generator(existing_summary=enabled)
        repo = cast(Any, generator._summary_repo)
        repo.find_by_contact_id = AsyncMock(side_effect=[enabled, user_disabled])
        repo.upsert_from_generation = AsyncMock(return_value=None)

        result = await generator.generate(contact_id=1)

        assert result is user_disabled
        assert generator._event_publisher is not None
        cast(AsyncMock, generator._event_publisher.publish).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_disable_before_auto_pause_keeps_their_choice(self):
        """Low activity never converts a concurrent user disable into a pause."""
        enabled = ContactSummary(contact_id=1, status=SummaryStatus.PENDING)
        user_disabled = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
        )
        generator = _make_generator(existing_summary=enabled, low_activity=True)
        repo = cast(Any, generator._summary_repo)
        repo.find_by_contact_id = AsyncMock(side_effect=[enabled, user_disabled])
        repo.upsert_from_generation = AsyncMock(return_value=None)

        result = await generator.generate(contact_id=1)

        assert result is user_disabled
        assert result.disabled_reason == SummaryDisabledReason.USER
        assert generator._event_publisher is not None
        cast(AsyncMock, generator._event_publisher.publish).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sets_generating_status_before_ai_call(self):
        """Test that status is set to GENERATING before calling AI."""
        generator = _make_generator()
        await generator.generate(contact_id=1)

        # Verify update_status was called with GENERATING
        generator._summary_repo.update_status_unless_user_disabled.assert_any_call(  # type: ignore[attr-defined]
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
        assert result.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY

        # Verify a ContactSummaryUpdated event was published with the disable diff.
        assert generator._event_publisher is not None
        publish_mock = cast(AsyncMock, generator._event_publisher.publish)
        publish_mock.assert_awaited_once()
        event = publish_mock.await_args_list[0].args[0]
        assert event.event_type == "ContactSummaryUpdated"
        assert event.event_data["contact_id"] == 1
        assert "is_disabled" in event.event_data["changed_fields"]

    @pytest.mark.asyncio
    async def test_user_disabled_contact_skipped(self):
        """A summary the user disabled (non-override) is skipped outright."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
            is_user_override=False,
        )
        generator = _make_generator(existing_summary=existing)

        result = await generator.generate(contact_id=1)

        # Should return the existing disabled summary without attempting generation
        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        cast(AsyncMock, generator._input_assembler.assemble).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_disabled_contact_with_override_skipped(self):
        """A user's disable is sticky even when the summary has a manual override."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.USER,
            is_user_override=True,
            user_override_text="My own summary",
        )
        generator = _make_generator(existing_summary=existing)

        result = await generator.generate(contact_id=1)

        assert result is existing
        assert result.disabled_reason == SummaryDisabledReason.USER
        cast(AsyncMock, generator._input_assembler.assemble).assert_not_awaited()
        cast(
            AsyncMock, generator._summary_repo.upsert_from_generation
        ).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_paused_contact_resumes_when_activity_recovers(self):
        """A low-activity pause is re-evaluated and lifted once activity is enough."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        generator = _make_generator(existing_summary=existing, low_activity=False)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert result.is_disabled is False
        assert result.disabled_reason is None
        assert generator._event_publisher is not None
        publish_mock = cast(AsyncMock, generator._event_publisher.publish)
        publish_mock.assert_awaited_once()
        changed_fields = (
            publish_mock.await_args_list[0].args[0].event_data["changed_fields"]
        )
        assert "summary_text" in changed_fields
        assert "is_disabled" in changed_fields

    @pytest.mark.asyncio
    async def test_auto_paused_contact_stays_paused_while_activity_low(self):
        """Still-low activity keeps the pause and records no new history."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        generator = _make_generator(existing_summary=existing, low_activity=True)

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.DISABLED
        assert result.disabled_reason == SummaryDisabledReason.LOW_ACTIVITY
        assert generator._event_publisher is not None
        cast(AsyncMock, generator._event_publisher.publish).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_paused_contact_without_journals_is_unchanged(self):
        """With nothing to summarise, a paused summary is left paused, not cleared."""
        existing = ContactSummary(
            contact_id=1,
            summary_text="Old text",
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        generator = _make_generator(
            existing_summary=existing,
            assembler_result=_make_input(recent_journals=[], future_journals=[]),
        )

        result = await generator.generate(contact_id=1)

        assert result is existing
        assert result.status == SummaryStatus.DISABLED
        cast(
            AsyncMock, generator._summary_repo.upsert_from_generation
        ).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_paused_contact_resumes_even_if_ai_call_fails(self):
        """Enough activity lifts the pause; a failed AI call is an ordinary FAILED."""
        existing = ContactSummary(
            contact_id=1,
            status=SummaryStatus.DISABLED,
            is_disabled=True,
            disabled_reason=SummaryDisabledReason.LOW_ACTIVITY,
        )
        generator = _make_generator(
            existing_summary=existing, gemini_response="INVALID_NOT_JSON"
        )

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.status == SummaryStatus.FAILED
        assert result.is_disabled is False
        assert result.disabled_reason is None

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
        generator._summary_repo.update_status_unless_user_disabled.assert_not_called()  # type: ignore[attr-defined]

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

    @pytest.mark.asyncio
    async def test_early_exit_when_no_journals_present(self):
        """Test that generation is skipped when no journals are available for the prompt."""
        generator = _make_generator()

        # Override assembler to return no journals
        empty_input = _make_input(recent_journals=[], future_journals=[])
        generator._input_assembler.assemble = AsyncMock(return_value=empty_input)  # type: ignore[method-assign]

        existing = ContactSummary(
            contact_id=1, status=SummaryStatus.GENERATED, summary_text="Old summary"
        )
        generator._summary_repo.find_by_contact_id = AsyncMock(return_value=existing)  # type: ignore[method-assign]

        result = await generator.generate(contact_id=1)

        assert result is not None
        assert result.summary_text == ""
        assert result.follow_up_suggestions == []
        assert result.status == SummaryStatus.GENERATED
        assert result.generated_at is not None

        # Ensure that it was saved with cleared data
        cast(
            AsyncMock, generator._summary_repo.upsert_from_generation
        ).assert_called_once_with(result)

        # Ensure full generation flow was skipped
        generator._summary_repo.update_status_unless_user_disabled.assert_not_called()  # type: ignore[attr-defined]
