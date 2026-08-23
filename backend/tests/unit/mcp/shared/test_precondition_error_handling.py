"""Unit tests for how the shared MCP error handler renders a write conflict.

Without a branch of its own a stale ``expected_version`` falls to the
decorator's catch-all and comes back as *"An error occurred while
update_journal_entry"* — indistinguishable from a server fault, so a model
would either give up or blindly retry the same doomed write. The refusal has to
say the resource moved on, and hand back the version to retry with.
"""

import json

from core_shared.exceptions import PreconditionFailedError

from app.mcp.shared.decorators import mcp_unified_error_handler


async def _render(error: Exception) -> dict[str, str]:
    @mcp_unified_error_handler("update_journal_entry", "journal")
    async def failing() -> str:
        raise error

    rendered: dict[str, str] = json.loads(await failing())
    return rendered


class TestConflictReachesTheClient:
    """A refused conditional write is reported as something to act on."""

    async def test_it_is_labelled_a_conflict_not_an_internal_error(self) -> None:
        response = await _render(PreconditionFailedError("journals", 42, '"current"'))

        assert response["error"] == "Conflict"
        assert response["code"] == "PRECONDITION_FAILED"

    async def test_the_message_says_what_to_do_next(self) -> None:
        response = await _render(PreconditionFailedError("journals", 42, '"current"'))

        assert "42" in response["message"]
        assert "re-read" in response["message"].lower()

    async def test_the_current_version_travels_with_the_refusal(self) -> None:
        """Named ``current_version`` to match the tools' ``expected_version``."""
        response = await _render(PreconditionFailedError("contacts", 7, '"current"'))

        assert response["current_version"] == '"current"'
        assert response["resource_type"] == "contacts"
        assert response["resource_id"] == "7"
