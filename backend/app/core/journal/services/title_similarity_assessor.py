"""Title similarity assessment protocol and Gemini implementation.

Defines the protocol for assessing similarity between two calendar events,
and provides a Gemini-based implementation using Google's generative AI.
"""

import asyncio
import re
from datetime import datetime
from typing import Protocol, runtime_checkable

import structlog

from app.core.settings.timezone_utils import DEFAULT_TIMEZONE, isoformat_in_tz

logger = structlog.get_logger()


class SimilarityAssessmentError(Exception):
    """Raised when a similarity assessment fails due to an unparseable response.

    This is a non-transient error that indicates the AI model returned a response
    that could not be interpreted as a valid similarity score. Callers should
    catch this to skip the failed candidate while allowing transport/API errors
    to propagate for outbox retry.
    """


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

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        timezone: str = DEFAULT_TIMEZONE,
    ) -> None:
        """Initialize with Gemini API credentials.

        Args:
            api_key: Google API key for Gemini access
            model: Gemini model to use (default: gemini-3.5-flash-lite)
            timezone: IANA timezone used to render event datetimes in prompts
        """
        self._api_key = api_key
        self._model = model
        self._timezone = timezone

    # Maximum characters of content/description to include in prompts.
    # Keeps prompt size bounded to avoid exceeding model token limits,
    # reduce latency/cost, and limit sensitive-data exposure.
    _MAX_CONTENT_CHARS = 2000

    @classmethod
    def _truncate_content(cls, content: str) -> str:
        """Truncate content to the maximum allowed length."""
        if len(content) <= cls._MAX_CONTENT_CHARS:
            return content
        return content[: cls._MAX_CONTENT_CHARS] + "... [truncated]"

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
        desc_a = self._truncate_content(content_a) if content_a else "(no description)"
        desc_b = self._truncate_content(content_b) if content_b else "(no description)"

        tz = self._timezone

        return f"""You are evaluating whether two calendar events refer to the same real-world event.
Compare the following two events and respond with ONLY a decimal number between 0.0 and 1.0
representing your confidence that they are the same event.

0.0 = Definitely different events
0.5 = Uncertain
1.0 = Definitely the same event

Consider: titles, descriptions, timing overlap, and duration similarity.
All times are shown in the user's local timezone with an explicit UTC offset.

Event A:
- Title: {title_a}
- Description: {desc_a}
- Start: {isoformat_in_tz(start_a, tz)}
- End: {isoformat_in_tz(end_a, tz)}

Event B:
- Title: {title_b}
- Description: {desc_b}
- Start: {isoformat_in_tz(start_b, tz)}
- End: {isoformat_in_tz(end_b, tz)}

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
            raise SimilarityAssessmentError(
                f"Gemini returned unparseable response for '{title_a}' vs '{title_b}'"
            )

        # Clamp to valid range
        return max(0.0, min(1.0, score))

    async def _call_gemini(self, prompt: str) -> float | None:
        """Call Gemini API and parse the response.

        Args:
            prompt: The prompt to send to Gemini

        Returns:
            Parsed float score or None if parsing fails

        Raises:
            asyncio.TimeoutError: If the call exceeds timeout after retries
            Exception: Transport/API errors are re-raised so the outbox
                       retry mechanism can handle transient outages.
        """
        from google import genai

        client = genai.Client(api_key=self._api_key)

        # Let transport / API / auth errors propagate for outbox retry.
        # Only swallow response-shape / parse errors below.
        max_attempts = 3
        base_delay = 1.0

        for attempt in range(max_attempts):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=self._model,
                        contents=prompt,
                    ),
                    timeout=self.TIMEOUT_SECONDS,
                )

                if response and response.text:
                    return self._parse_score(response.text)

                logger.warning("Gemini returned empty response")
                return None

            except Exception as e:
                if attempt == max_attempts - 1:
                    raise

                delay = base_delay * (2**attempt)
                logger.warning(
                    "Gemini API error, retrying",
                    delay_seconds=delay,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    error=str(e),
                )
                await asyncio.sleep(delay)

        raise RuntimeError("Unreachable")

    @staticmethod
    def _parse_score(text: str) -> float | None:
        """Parse a float score from Gemini's text response.

        Only matches numbers in the valid [0.0, 1.0] range to avoid
        picking up unrelated numbers like years or timestamps.

        Args:
            text: Raw text response from Gemini

        Returns:
            Parsed float or None if parsing fails
        """
        try:
            # Match numbers that could be valid scores: 0, 0.x, 1, 1.0
            # Rejects values > 1.0 (e.g. years like 2026) at the regex level
            matches = re.findall(r"\b([01]\.?\d*)\b", text.strip())
            for m in matches:
                val = float(m)
                if 0.0 <= val <= 1.0:
                    return val
            return None
        except ValueError, AttributeError:
            return None
