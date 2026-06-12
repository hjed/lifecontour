"""Integration tests for DailySummaryService against a real database.

Exercises the ``get_or_generate`` pipeline end-to-end through real SQL. Each
write (the ``GENERATING`` marker and the final ``GENERATED``/``FAILED`` result)
commits as its own short unit of work so no transaction is held across the AI
call (issue #970); before issue #945's fix the REST controller also left these
writes uncommitted, discarding the summary at request teardown. The AI call and
input assembly are stubbed; the repository and connection are real.
"""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_service import DailySummaryService

_USER = "user_ds_integ"
_DATE = date(2026, 4, 27)


@pytest.mark.integration
class TestDailySummaryServiceTransactionalIntegration:
    """get_or_generate / regenerate commit their writes via the service layer."""

    @pytest.fixture
    def service(self, async_connection):
        assembler = AsyncMock()
        assembler.assemble.return_value = DailySummaryInput(
            user_id=_USER,
            summary_date=_DATE,
            journals=[],
            journal_count=2,
            event_count=1,
            contact_names=["Alice"],
            mood_values=[7, 8],
        )
        eligibility = MagicMock()
        eligibility.is_eligible.return_value = True
        prompt_builder = MagicMock()
        prompt_builder.build.return_value = "prompt"
        return DailySummaryService(
            input_assembler=assembler,
            eligibility_checker=eligibility,
            prompt_builder=prompt_builder,
            summary_repo=SqlJournalDailySummaryRepository(async_connection),
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-pro",
            _gemini_response_override=json.dumps({"summary_text": "A productive day."}),
        )

    @pytest.mark.asyncio
    async def test_get_or_generate_persists_generated_summary(
        self, service, async_connection
    ):
        """A freshly generated summary is durably written through real SQL."""
        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED

        # Read back via a separate repo on the same connection: the final
        # result's unit of work released its savepoint, so the row is present
        # (it was not rolled back as an uncommitted write would be).
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(_USER, _DATE)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATED
        assert persisted.summary_text == "A productive day."

    @pytest.mark.asyncio
    async def test_marks_generating_before_calling_gemini(
        self, service, async_connection
    ):
        """The GENERATING marker commits before the AI call, holding no txn.

        Issue #970: the multi-second Gemini call must not run inside the unit of
        work. We stub ``_call_gemini`` to observe state at AI-call time: the row
        is already GENERATING (its marker committed as its own unit of work) and
        no unit of work is open on the connection (depth 0).
        """
        observed: dict[str, object] = {}

        async def fake_gemini(prompt: str) -> str:
            repo = SqlJournalDailySummaryRepository(async_connection)
            row = await repo.find_by_user_and_date(_USER, _DATE)
            observed["status"] = row.status if row else None
            observed["uow_depth"] = async_connection.info.get("uow_depth", 0)
            return json.dumps({"summary_text": "A productive day."})

        service._call_gemini = fake_gemini

        result = await service.get_or_generate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        # The marker was committed (visible on the same connection) before Gemini
        assert observed["status"] == SummaryStatus.GENERATING
        # ...and no transaction was held across the AI call.
        assert observed["uow_depth"] == 0

    @pytest.mark.asyncio
    async def test_regenerate_overwrites_existing_summary(
        self, service, async_connection
    ):
        """regenerate invalidates then re-persists as separate committed units."""
        await service.get_or_generate(_USER, _DATE, async_connection)

        result = await service.regenerate(_USER, _DATE, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        repo = SqlJournalDailySummaryRepository(async_connection)
        persisted = await repo.find_by_user_and_date(_USER, _DATE)
        assert persisted is not None
        assert persisted.status == SummaryStatus.GENERATED
