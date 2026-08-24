"""Rejections an agent can act on, rather than a bare "Internal error".

``mcp_unified_error_handler`` matches domain errors and ``ValueError`` and
reports everything else through a catch-all that says only "An error occurred".
Two kinds of failure fell through it and lost the one line that said what was
wrong: an ``HTTPException`` raised out of a service, and the database refusing
a value for its column. Both are bad input, and both now name what was wrong.
"""

import json

import pydantic
import pytest
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import DataError

from app.mcp.shared.decorators import mcp_unified_error_handler


@pytest.mark.asyncio
async def test_http_exception_is_reported_as_a_validation_error() -> None:
    """A stray HTTPException must not be flattened into "Internal error"."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise HTTPException(status_code=400, detail="mood_value must be an integer")

    payload = json.loads(await tool())

    assert payload["error"] == "Validation error"
    assert payload["message"] == "mood_value must be an integer"
    assert payload["status_code"] == 400


@pytest.mark.asyncio
async def test_database_rejection_names_the_constraint() -> None:
    """The driver's reason is actionable; "Internal error" is not."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise DataError(
            "INSERT INTO journal_outdoor_activity_data ...",
            {"role": "x" * 101},
            Exception("value too long for type character varying(100)"),
        )

    payload = json.loads(await tool())

    assert payload["error"] == "Validation error"
    assert "character varying(100)" in payload["message"]


@pytest.mark.asyncio
async def test_database_rejection_does_not_echo_the_statement() -> None:
    """The SQL and the bound values belong in the log, not the response."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise DataError(
            "INSERT INTO journal_outdoor_activity_data (role) VALUES ($1)",
            {"role": "secret-value"},
            Exception("value too long for type character varying(100)"),
        )

    payload = json.loads(await tool())

    assert "INSERT INTO" not in payload["message"]
    assert "secret-value" not in payload["message"]


@pytest.mark.asyncio
async def test_database_rejection_redacts_a_quoted_literal() -> None:
    """Postgres quotes the rejected value into the message itself.

    Truncation happens to name no value, so a test built only on that one
    passes without the code guaranteeing anything. These messages carry the
    caller's own submitted data in their first line, and the handlers they
    reach are global — so the literal has to be redacted, not merely left
    un-repeated.
    """

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise DataError(
            "INSERT INTO journals (id) VALUES ($1)",
            {"id": "patient-4821-078051120"},
            Exception('invalid input syntax for type uuid: "patient-4821-078051120"'),
        )

    payload = json.loads(await tool())

    assert "patient-4821-078051120" not in payload["message"]
    # The shape of the failure is what makes it actionable, so it survives.
    assert "invalid input syntax for type uuid" in payload["message"]


@pytest.mark.asyncio
async def test_a_value_containing_a_quote_cannot_slip_past_redaction() -> None:
    """Postgres interpolates the value verbatim, so quoting can be unbalanced.

    A submitted `prefix"secret` renders as ... "prefix"secret", and pairing the
    quotes off would redact "prefix" and hand `secret` straight back. The span
    runs first-quote-to-last so nothing inside can survive.
    """

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise DataError(
            "INSERT INTO journals (id) VALUES ($1)",
            {"id": 'prefix"secret-078051120'},
            Exception('invalid input syntax for type uuid: "prefix"secret-078051120"'),
        )

    payload = json.loads(await tool())

    assert "secret" not in payload["message"]
    assert "078051120" not in payload["message"]
    assert "invalid input syntax for type uuid" in payload["message"]


@pytest.mark.asyncio
async def test_text_after_the_quoted_value_is_kept() -> None:
    """Redaction must not swallow the half of the message that is actionable."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise DataError(
            "INSERT INTO journal_fitness_data (distance) VALUES ($1)",
            {"distance": "99999999999"},
            Exception('value "99999999999" is out of range for type integer'),
        )

    payload = json.loads(await tool())

    assert "99999999999" not in payload["message"]
    assert "is out of range for type integer" in payload["message"]


@pytest.mark.asyncio
async def test_every_schema_rejection_is_reported() -> None:
    """Three wrong fields should not need three round trips to discover."""

    class Payload(BaseModel):
        first: int = Field(ge=1)
        second: int = Field(ge=1)
        third: int = Field(ge=1)

    @mcp_unified_error_handler("create_journal_entry", "journal")
    async def tool() -> str:
        Payload.model_validate({"first": 0, "second": 0, "third": 0})
        return "{}"

    payload = json.loads(await tool())

    assert payload["error"] == "Validation error"
    for field in ("first", "second", "third"):
        assert field in payload["message"]


@pytest.mark.asyncio
async def test_an_unexpected_error_is_still_reported_as_internal() -> None:
    """The nets are for bad input; a real fault stays a fault."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise RuntimeError("the disk caught fire")

    payload = json.loads(await tool())

    assert payload["error"] == "Internal error"
    assert "disk caught fire" not in payload["message"]


@pytest.mark.asyncio
async def test_a_pydantic_error_with_no_details_still_answers() -> None:
    """Defensive: an empty error list must not crash the handler itself."""

    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def tool() -> str:
        raise pydantic.ValidationError.from_exception_data("Payload", [])

    payload = json.loads(await tool())

    assert payload["error"] == "Validation error"
