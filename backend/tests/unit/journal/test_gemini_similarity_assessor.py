"""Unit tests for GeminiTitleSimilarityAssessor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.core.journal.services.title_similarity_assessor import (
    GeminiTitleSimilarityAssessor,
    SimilarityAssessmentError,
)


@pytest.mark.unit
class TestGeminiTitleSimilarityAssessor:
    """Test Gemini-based title similarity assessment."""

    @pytest.fixture
    def assessor(self) -> GeminiTitleSimilarityAssessor:
        """Create an assessor with a test API key."""
        return GeminiTitleSimilarityAssessor(
            api_key="test-api-key", model="gemini-2.5-flash"
        )

    @pytest.fixture
    def sample_dates(self) -> dict[str, datetime]:
        """Create sample dates for testing."""
        return {
            "start_a": datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
            "end_a": datetime(2024, 3, 15, 11, 0, 0, tzinfo=UTC),
            "start_b": datetime(2024, 3, 15, 10, 0, 0, tzinfo=UTC),
            "end_b": datetime(2024, 3, 15, 11, 0, 0, tzinfo=UTC),
        }

    async def test_returns_float_score(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that assess_similarity returns a float between 0 and 1."""
        with patch.object(
            assessor, "_call_gemini", new_callable=AsyncMock, return_value=0.85
        ):
            score = await assessor.assess_similarity(
                title_a="Team Meeting",
                content_a="Weekly team sync",
                start_a=sample_dates["start_a"],
                end_a=sample_dates["end_a"],
                title_b="Team Meeting (Updated)",
                content_b="Weekly team sync - updated agenda",
                start_b=sample_dates["start_b"],
                end_b=sample_dates["end_b"],
            )

            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0
            assert score == 0.85

    async def test_builds_prompt_with_all_fields(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that the prompt includes titles, content, and dates."""
        captured_prompt = None

        async def capture_prompt(prompt: str) -> float:
            nonlocal captured_prompt
            captured_prompt = prompt
            return 0.5

        with patch.object(assessor, "_call_gemini", side_effect=capture_prompt):
            await assessor.assess_similarity(
                title_a="Team Meeting",
                content_a="Weekly sync discussion",
                start_a=sample_dates["start_a"],
                end_a=sample_dates["end_a"],
                title_b="Weekly Team Meeting",
                content_b="Team discussion agenda",
                start_b=sample_dates["start_b"],
                end_b=sample_dates["end_b"],
            )

        assert captured_prompt is not None
        assert "Team Meeting" in captured_prompt
        assert "Weekly Team Meeting" in captured_prompt
        assert "Weekly sync discussion" in captured_prompt
        assert "Team discussion agenda" in captured_prompt
        # Dates should be present in some format
        assert "2024" in captured_prompt

    async def test_prompt_renders_dates_in_user_timezone(
        self,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Event datetimes are rendered in the configured timezone with offset."""
        assessor = GeminiTitleSimilarityAssessor(
            api_key="test-api-key",
            model="gemini-2.5-flash",
            timezone="Australia/Sydney",
        )
        captured_prompt = None

        async def capture_prompt(prompt: str) -> float:
            nonlocal captured_prompt
            captured_prompt = prompt
            return 0.5

        with patch.object(assessor, "_call_gemini", side_effect=capture_prompt):
            await assessor.assess_similarity(
                title_a="A",
                content_a="",
                start_a=sample_dates["start_a"],
                end_a=sample_dates["end_a"],
                title_b="B",
                content_b="",
                start_b=sample_dates["start_b"],
                end_b=sample_dates["end_b"],
            )

        assert captured_prompt is not None
        # 10:00 UTC -> 21:00 Sydney (AEDT, +11:00 in March)
        assert "2024-03-15T21:00:00+11:00" in captured_prompt

    async def test_handles_gemini_error(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that an error from Gemini raises an appropriate error."""
        with patch.object(
            assessor,
            "_call_gemini",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Gemini call failed"),
        ):
            with pytest.raises(RuntimeError):
                await assessor.assess_similarity(
                    title_a="Event A",
                    content_a="",
                    start_a=sample_dates["start_a"],
                    end_a=sample_dates["end_a"],
                    title_b="Event B",
                    content_b="",
                    start_b=sample_dates["start_b"],
                    end_b=sample_dates["end_b"],
                )

    async def test_unparseable_response_raises_assessment_error(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that an unparseable Gemini response raises SimilarityAssessmentError."""
        with patch.object(
            assessor,
            "_call_gemini",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(SimilarityAssessmentError):
                await assessor.assess_similarity(
                    title_a="Event A",
                    content_a="",
                    start_a=sample_dates["start_a"],
                    end_a=sample_dates["end_a"],
                    title_b="Event B",
                    content_b="",
                    start_b=sample_dates["start_b"],
                    end_b=sample_dates["end_b"],
                )

    async def test_clamps_score_above_one(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that scores above 1.0 from Gemini are clamped."""
        with patch.object(
            assessor, "_call_gemini", new_callable=AsyncMock, return_value=1.5
        ):
            score = await assessor.assess_similarity(
                title_a="Event A",
                content_a="",
                start_a=sample_dates["start_a"],
                end_a=sample_dates["end_a"],
                title_b="Event A",
                content_b="",
                start_b=sample_dates["start_b"],
                end_b=sample_dates["end_b"],
            )

            assert score == 1.0

    async def test_clamps_score_below_zero(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that scores below 0.0 from Gemini are clamped."""
        with patch.object(
            assessor, "_call_gemini", new_callable=AsyncMock, return_value=-0.3
        ):
            score = await assessor.assess_similarity(
                title_a="Event A",
                content_a="",
                start_a=sample_dates["start_a"],
                end_a=sample_dates["end_a"],
                title_b="Event B",
                content_b="",
                start_b=sample_dates["start_b"],
                end_b=sample_dates["end_b"],
            )

            assert score == 0.0

    async def test_call_gemini_retries_on_error(
        self,
        assessor: GeminiTitleSimilarityAssessor,
    ) -> None:
        """Test that _call_gemini retries on Exception before failing."""
        from unittest.mock import MagicMock

        with patch("google.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Make the async call raise RuntimeError every time
            # We mock asyncio.wait_for instead, because the error is raised by wait_for
            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait_for:
                mock_wait_for.side_effect = RuntimeError("API Error")

                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    with pytest.raises(RuntimeError):
                        await assessor._call_gemini("test prompt")

                    # Should have been called 3 times (initial + 2 retries)
                    assert mock_wait_for.call_count == 3

                    # Should have slept twice (1s, 2s)
                    assert mock_sleep.call_count == 2
                    mock_sleep.assert_any_call(1.0)
                    mock_sleep.assert_any_call(2.0)
