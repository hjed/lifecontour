"""Unit tests for how an MCP request resolves the acting user.

Under the generic-OAuth proxy the verified ``AccessToken`` carries the upstream
identity under ``claims["upstream_claims"]`` — FastMCP re-attaches it there from
the FastMCP JWT on every verified request. ``get_session_user`` must read that
nested block, because the flat claims hold only the raw upstream token.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.shared.dependencies import get_current_user_id, get_session_user


def _token(claims: dict[str, Any], client_id: str = "debug-client") -> MagicMock:
    token = MagicMock()
    token.claims = claims
    token.client_id = client_id
    return token


def _with_access_token(token: MagicMock | None) -> Any:
    """Patch the FastMCP dependency ``get_session_user`` imports at call time."""
    return patch(
        "fastmcp.server.dependencies.get_access_token",
        return_value=token,
    )


class TestSessionUserFromUpstreamClaims:
    async def test_uses_the_upstream_subject_as_the_user_id(self) -> None:
        token = _token(
            {
                "token": "opaque-upstream-token",
                "upstream_claims": {
                    "sub": "9f1c1f0e-0000-4000-8000-abcdefabcdef",
                    "email": "person@example.com",
                    "name": "A Person",
                },
            }
        )

        with _with_access_token(token):
            user = await get_session_user()

        assert user.id == "9f1c1f0e-0000-4000-8000-abcdefabcdef"
        assert user.email == "person@example.com"
        assert user.name == "A Person"
        assert user.provider == "mcp-oauth"

    async def test_current_user_id_is_the_upstream_subject(self) -> None:
        token = _token({"upstream_claims": {"sub": "upstream-subject"}})

        with _with_access_token(token):
            assert await get_current_user_id() == "upstream-subject"

    async def test_flat_claims_still_work_for_named_providers(self) -> None:
        """GitHub/Azure/Discord verify upstream themselves and expose flat claims."""
        token = _token({"sub": "flat-subject", "email": "a@b.com"}, client_id="gh-app")

        with _with_access_token(token):
            user = await get_session_user()

        assert user.id == "flat-subject"

    async def test_upstream_claims_win_over_flat_claims(self) -> None:
        token = _token(
            {"sub": "flat-subject", "upstream_claims": {"sub": "upstream-subject"}}
        )

        with _with_access_token(token):
            user = await get_session_user()

        assert user.id == "upstream-subject"

    async def test_token_without_any_identity_is_refused(self) -> None:
        """The pre-fix shape: no identity anywhere, only the raw upstream token.

        It must raise rather than resolve to the verifier's ``client_id``
        default, which is how every MCP write ended up owned by
        ``"debug-client"``.
        """
        with _with_access_token(_token({"token": "opaque-upstream-token"})):
            with pytest.raises(ValueError, match="identifier"):
                await get_session_user()
