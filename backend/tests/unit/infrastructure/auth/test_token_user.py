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

    def test_id_falls_back_to_id_then_client_id(self) -> None:
        assert (
            session_user_from_claims(
                {"id": "alt-id"}, client_id="client-abc", provider="p"
            ).id
            == "alt-id"
        )

        assert (
            session_user_from_claims({}, client_id="client-abc", provider="p").id
            == "client-abc"
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

    def test_none_claims_treated_as_empty(self) -> None:
        user = session_user_from_claims(None, client_id="client-abc", provider="p")
        assert user.id == "client-abc"

    def test_raises_when_no_identifier(self) -> None:
        with pytest.raises(ValueError, match="identifier"):
            session_user_from_claims({"email": "a@b.com"}, client_id=None, provider="p")
