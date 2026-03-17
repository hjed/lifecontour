"""Title similarity assessment protocol and Gemini implementation.

Defines the protocol for assessing similarity between two calendar events,
and provides a Gemini-based implementation using Google's generative AI.
"""

import asyncio
import re
from datetime import datetime
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


@runtime_checkable
class TitleSimilarityAssessor(Protocol):
    """Protocol for assessing similarity between two calendar events.

    Implementations compare two events using their titles, content/descriptions,
    and date/time ranges to determine if they likely refer to the same real-world event.
    """

    async def assess_similarity(
        self,
        title_a: str,
        content_a: str,
        start_a: datetime,
        end_a: datetime,
        title_b: str,
        content_b: str,
        start_b: datetime,
        end_b: datetime,
    ) -> float:
        """Assess similarity between two events.

        Args:
            title_a: Title of the first event
            content_a: Content/description of the first event
            start_a: Start datetime of the first event
            end_a: End datetime of the first event
            title_b: Title of the second event
            content_b: Content/description of the second event
            start_b: Start datetime of the second event
            end_b: End datetime of the second event

        Returns:
            Float between 0.0 and 1.0 indicating confidence that the two
            events refer to the same real-world event.
        """
        ...


class GeminiTitleSimilarityAssessor:
    """Assesses event similarity using Google Gemini.

    Sends both events' details to Gemini and asks it to evaluate whether
    they refer to the same real-world event. Returns a confidence score.
    """

    TIMEOUT_SECONDS = 10.0

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        """Initialize with Gemini API credentials.

        Args:
            api_key: Google API key for Gemini access
            model: Gemini model to use (default: gemini-2.0-flash)
        """
        self._api_key = api_key
        self._model = model

    def _build_prompt(
        self,
        title_a: str,
        content_a: str,
        start_a: datetime,
        end_a: datetime,
        title_b: str,
        content_b: str,
        start_b: datetime,
        end_b: datetime,
    ) -> str:
        """Build the comparison prompt for Gemini.

        Args:
            title_a: Title of event A
            content_a: Content of event A
            start_a: Start time of event A
            end_a: End time of event A
            title_b: Title of event B
            content_b: Content of event B
            start_b: Start time of event B
            end_b: End time of event B

        Returns:
            Formatted prompt string
        """
        return f"""You are evaluating whether two calendar events refer to the same real-world event.
Compare the following two events and respond with ONLY a decimal number between 0.0 and 1.0
representing your confidence that they are the same event.

0.0 = Definitely different events
0.5 = Uncertain
1.0 = Definitely the same event

Consider: titles, descriptions, timing overlap, and duration similarity.

Event A:
- Title: {title_a}
- Description: {content_a or "(no description)"}
- Start: {start_a.isoformat()}
- End: {end_a.isoformat()}

Event B:
- Title: {title_b}
- Description: {content_b or "(no description)"}
- Start: {start_b.isoformat()}
- End: {end_b.isoformat()}

Confidence score (0.0-1.0):"""

    async def assess_similarity(
        self,
        title_a: str,
        content_a: str,
        start_a: datetime,
        end_a: datetime,
        title_b: str,
        content_b: str,
        start_b: datetime,
        end_b: datetime,
    ) -> float:
        """Assess similarity between two events using Gemini.

        Args:
            title_a: Title of the first event
            content_a: Content/description of the first event
            start_a: Start datetime of the first event
            end_a: End datetime of the first event
            title_b: Title of the second event
            content_b: Content/description of the second event
            start_b: Start datetime of the second event
            end_b: End datetime of the second event

        Returns:
            Float between 0.0 and 1.0.

        Raises:
            asyncio.TimeoutError: If Gemini call exceeds timeout
        """
        prompt = self._build_prompt(
            title_a,
            content_a,
            start_a,
            end_a,
            title_b,
            content_b,
            start_b,
            end_b,
        )

        score = await self._call_gemini(prompt)

        if score is None:
            logger.warning(
                "Gemini returned invalid response, defaulting to 0.0",
                title_a=title_a,
                title_b=title_b,
            )
            return 0.0

        # Clamp to valid range
        return max(0.0, min(1.0, score))

    async def _call_gemini(self, prompt: str) -> float | None:
        """Call Gemini API and parse the response.

        Args:
            prompt: The prompt to send to Gemini

        Returns:
            Parsed float score or None if parsing fails

        Raises:
            asyncio.TimeoutError: If the call exceeds timeout
        """
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model)

            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, prompt),
                timeout=self.TIMEOUT_SECONDS,
            )

            if response and response.text:
                return self._parse_score(response.text)
            return None

        except TimeoutError:
            logger.error("Gemini API call timed out", timeout=self.TIMEOUT_SECONDS)
            raise
        except Exception as e:
            logger.error("Gemini API call failed", error=str(e))
            return None

    @staticmethod
    def _parse_score(text: str) -> float | None:
        """Parse a float score from Gemini's text response.

        Args:
            text: Raw text response from Gemini

        Returns:
            Parsed float or None if parsing fails
        """
        try:
            # Try to find a decimal number in the response
            match = re.search(r"(\d+\.?\d*)", text.strip())
            if match:
                return float(match.group(1))
            return None
        except (ValueError, AttributeError):
            return None
