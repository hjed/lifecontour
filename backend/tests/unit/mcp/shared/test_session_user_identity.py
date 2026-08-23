"""Unit tests for how an MCP request resolves the acting user.

Every provider exposes identity the same way: as flat claims on the verified
``AccessToken``. The named providers verify upstream themselves, and the
generic-OAuth proxy verifies the upstream ``id_token`` against the IdP's JWKS,
so the person who logged in is named by a claim we have actually checked the
signature of — never by the OAuth client the request arrived through.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.shared.dependencies import get_current_user_id, get_session_user


def _token(claims: dict[str, Any], client_id: str = "mcp-client") -> MagicMock:
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


class TestSessionUserFromVerifiedClaims:
    async def test_uses_the_verified_subject_as_the_user_id(self) -> None:
        token = _token(
            {
                "sub": "9f1c1f0e-0000-4000-8000-abcdefabcdef",
                "email": "person@example.com",
                "name": "A Person",
                "aud": "generic-id",
            }
        )

        with _with_access_token(token):
            user = await get_session_user()

        assert user.id == "9f1c1f0e-0000-4000-8000-abcdefabcdef"
        assert user.email == "person@example.com"
        assert user.name == "A Person"
        assert user.provider == "mcp-oauth"

    async def test_current_user_id_is_the_verified_subject(self) -> None:
        with _with_access_token(_token({"sub": "upstream-subject"})):
            assert await get_current_user_id() == "upstream-subject"

    async def test_named_provider_claims_resolve_the_same_way(self) -> None:
        """GitHub/Azure/Discord verify upstream themselves, same flat shape."""
        token = _token({"sub": "flat-subject", "email": "a@b.com"}, client_id="gh-app")

        with _with_access_token(token):
            user = await get_session_user()

        assert user.id == "flat-subject"

    async def test_token_without_any_identity_is_refused(self) -> None:
        """The pre-fix shape: no identity anywhere, only the raw upstream token.

        It must raise rather than resolve to the verifier's ``client_id``
        default, which is how every MCP write ended up owned by
        ``"debug-client"``.
        """
        with _with_access_token(_token({"token": "opaque-upstream-token"})):
            with pytest.raises(ValueError, match="identifier"):
                await get_session_user()

    async def test_the_client_id_never_becomes_the_user(self) -> None:
        """It names the application, never the person holding the session."""
        with _with_access_token(_token({}, client_id="some-registered-client")):
            with pytest.raises(ValueError, match="identifier"):
                await get_session_user()
