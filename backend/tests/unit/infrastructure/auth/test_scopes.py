"""Unit tests for API scope model and helpers."""

import pytest

from app.infrastructure.auth.scopes import (
    ApiScope,
    recognized_scopes,
    required_scope_for_method,
    token_satisfies,
)


class TestApiScopeValues:
    """The scope enum values are app-prefixed."""

    def test_scope_string_values(self) -> None:
        assert ApiScope.READ.value == "pms_read"
        assert ApiScope.WRITE.value == "pms_write"
        assert ApiScope.ADMIN.value == "pms_admin"


class TestRequiredScopeForMethod:
    """Safe methods require read; mutating methods require write."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get", "head"])
    def test_safe_methods_require_read(self, method: str) -> None:
        assert required_scope_for_method(method) == ApiScope.READ

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
    def test_mutating_methods_require_write(self, method: str) -> None:
        assert required_scope_for_method(method) == ApiScope.WRITE


class TestTokenSatisfies:
    """Scope hierarchy: pms_admin > pms_write > pms_read."""

    def test_read_grants_read_only(self) -> None:
        granted = {ApiScope.READ.value}
        assert token_satisfies(granted, ApiScope.READ)
        assert not token_satisfies(granted, ApiScope.WRITE)
        assert not token_satisfies(granted, ApiScope.ADMIN)

    def test_write_grants_read_and_write(self) -> None:
        granted = {ApiScope.WRITE.value}
        assert token_satisfies(granted, ApiScope.READ)
        assert token_satisfies(granted, ApiScope.WRITE)
        assert not token_satisfies(granted, ApiScope.ADMIN)

    def test_admin_grants_everything(self) -> None:
        granted = {ApiScope.ADMIN.value}
        assert token_satisfies(granted, ApiScope.READ)
        assert token_satisfies(granted, ApiScope.WRITE)
        assert token_satisfies(granted, ApiScope.ADMIN)

    def test_explicit_scopes_combine(self) -> None:
        granted = {ApiScope.READ.value, ApiScope.WRITE.value}
        assert token_satisfies(granted, ApiScope.WRITE)
        assert not token_satisfies(granted, ApiScope.ADMIN)

    def test_no_scopes_satisfies_nothing(self) -> None:
        assert not token_satisfies(set(), ApiScope.READ)


class TestRecognizedScopes:
    """Only known ApiScope values count as recognized API scopes."""

    def test_filters_to_known_api_scopes(self) -> None:
        granted = {"openid", "profile", "pms_read", "pms_admin", "email"}
        assert recognized_scopes(granted) == {"pms_read", "pms_admin"}

    def test_ignores_unrelated_pms_prefixed_scope(self) -> None:
        # An unrelated pms_* scope is not a recognized permission.
        assert recognized_scopes({"pms_something_else", "pms_read"}) == {"pms_read"}

    def test_empty_when_no_api_scopes(self) -> None:
        assert recognized_scopes({"openid", "profile", "email"}) == set()
