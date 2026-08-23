"""Unit tests for the shared OAuth-claims -> SessionUser mapping."""

import pytest

from app.infrastructure.auth.token_user import session_user_from_claims


class TestSessionUserFromClaims:
    """Claims are mapped onto SessionUser with documented fallbacks."""

    def test_maps_standard_oidc_claims(self) -> None:
        user = session_user_from_claims(
            {"sub": "user-123", "email": "a@example.com", "name": "Ada"},
            client_id="client-abc",
            provider="oauth-token",
        )
        assert user.id == "user-123"
        assert user.email == "a@example.com"
        assert user.name == "Ada"
        assert user.provider == "oauth-token"

    def test_id_falls_back_to_the_id_claim(self) -> None:
        assert (
            session_user_from_claims(
                {"id": "alt-id"}, client_id="client-abc", provider="p"
            ).id
            == "alt-id"
        )

    def test_client_id_is_never_a_user_identity(self) -> None:
        """A client id identifies the application, never the person using it.

        Accepting it as the last fallback is what silently attributed five
        months of MCP writes to a phantom owner (see
        ``test_debug_verifier_shaped_claims_are_refused``).
        """
        with pytest.raises(ValueError, match="identifier"):
            session_user_from_claims({}, client_id="client-abc", provider="p")

    def test_debug_verifier_shaped_claims_are_refused(self) -> None:
        """The exact shape ``DebugTokenVerifier`` produces must not authenticate.

        It returns ``claims={"token": <raw upstream token>}`` and its default
        ``client_id="debug-client"``, so before this guard every MCP request
        resolved to the literal user id ``"debug-client"``.
        """
        with pytest.raises(ValueError, match="identifier"):
            session_user_from_claims(
                {"token": "opaque-upstream-token"},
                client_id="debug-client",
                provider="mcp-oauth",
            )

    def test_name_falls_back_to_login_then_username(self) -> None:
        assert (
            session_user_from_claims(
                {"sub": "x", "login": "octocat"}, client_id=None, provider="p"
            ).name
            == "octocat"
        )

        assert (
            session_user_from_claims(
                {"sub": "x", "username": "uname"}, client_id=None, provider="p"
            ).name
            == "uname"
        )

    def test_missing_email_becomes_empty_string(self) -> None:
        user = session_user_from_claims({"sub": "x"}, client_id=None, provider="p")
        assert user.email == ""

    def test_null_email_claim_becomes_empty_string(self) -> None:
        user = session_user_from_claims(
            {"sub": "x", "email": None}, client_id=None, provider="p"
        )
        assert user.email == ""

    def test_none_claims_are_refused(self) -> None:
        with pytest.raises(ValueError, match="identifier"):
            session_user_from_claims(None, client_id="client-abc", provider="p")

    def test_raises_when_no_identifier(self) -> None:
        with pytest.raises(ValueError, match="identifier"):
            session_user_from_claims({"email": "a@b.com"}, client_id=None, provider="p")
