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
        assert ApiScope.READ.value == "pms:read"
        assert ApiScope.WRITE.value == "pms:write"
        assert ApiScope.ADMIN.value == "pms:admin"


class TestRequiredScopeForMethod:
    """Safe methods require read; mutating methods require write."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get", "head"])
    def test_safe_methods_require_read(self, method: str) -> None:
        assert required_scope_for_method(method) == ApiScope.READ

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
    def test_mutating_methods_require_write(self, method: str) -> None:
        assert required_scope_for_method(method) == ApiScope.WRITE


class TestTokenSatisfies:
    """Scope hierarchy: pms:admin > pms:write > pms:read."""

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
    """Only the pms:* subset counts as recognized API scopes."""

    def test_filters_to_pms_scopes(self) -> None:
        granted = {"openid", "profile", "pms:read", "pms:admin", "email"}
        assert recognized_scopes(granted) == {"pms:read", "pms:admin"}

    def test_empty_when_no_pms_scopes(self) -> None:
        assert recognized_scopes({"openid", "profile", "email"}) == set()
