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
            api_key="test-api-key", model="gemini-2.0-flash"
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

    async def test_handles_gemini_timeout(
        self,
        assessor: GeminiTitleSimilarityAssessor,
        sample_dates: dict[str, datetime],
    ) -> None:
        """Test that a timeout from Gemini raises an appropriate error."""
        import asyncio

        with patch.object(
            assessor,
            "_call_gemini",
            new_callable=AsyncMock,
            side_effect=TimeoutError("Gemini call timed out"),
        ):
            with pytest.raises(asyncio.TimeoutError):
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
