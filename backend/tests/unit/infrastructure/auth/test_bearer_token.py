"""Unit tests for bearer-token verifier construction via OIDC discovery."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from app.infrastructure.auth.bearer_token import create_jwt_verifier, discovery_url
from app.infrastructure.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"oauth_issuer": "", "oauth_discovery_url": ""}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestDiscoveryUrl:
    def test_empty_when_no_issuer(self) -> None:
        assert discovery_url(_settings()) == ""

    def test_derived_from_issuer(self) -> None:
        url = discovery_url(_settings(oauth_issuer="https://idp.example.com/"))
        assert url == "https://idp.example.com/.well-known/openid-configuration"

    def test_explicit_override_wins(self) -> None:
        url = discovery_url(
            _settings(
                oauth_issuer="https://idp.example.com",
                oauth_discovery_url="https://idp.example.com/custom/.well-known",
            )
        )
        assert url == "https://idp.example.com/custom/.well-known"


@asynccontextmanager
async def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield client


class TestCreateJwtVerifier:
    async def test_returns_none_without_issuer(self) -> None:
        assert await create_jwt_verifier(_settings()) is None

    async def test_builds_verifier_from_discovery(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/.well-known/openid-configuration"
            return httpx.Response(
                200,
                json={
                    "issuer": "https://idp.example.com",
                    "jwks_uri": "https://idp.example.com/jwks",
                },
            )

        async with _mock_client(handler) as client:
            verifier = await create_jwt_verifier(
                _settings(
                    oauth_issuer="https://idp.example.com",
                    oauth_audience="pms-api",
                ),
                http_client=client,
            )
        assert verifier is not None

    async def test_raises_on_missing_jwks_uri(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"issuer": "https://idp.example.com"})

        async with _mock_client(handler) as client:
            with pytest.raises(RuntimeError, match="jwks_uri"):
                await create_jwt_verifier(
                    _settings(oauth_issuer="https://idp.example.com"),
                    http_client=client,
                )

    async def test_raises_on_discovery_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        async with _mock_client(handler) as client:
            with pytest.raises(RuntimeError, match="discovery"):
                await create_jwt_verifier(
                    _settings(oauth_issuer="https://idp.example.com"),
                    http_client=client,
                )

    async def test_raises_on_issuer_mismatch(self) -> None:
        # A discovery document advertising a different issuer must fail closed
        # so attacker-controlled keys are never trusted.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "issuer": "https://evil.example.com",
                    "jwks_uri": "https://evil.example.com/jwks",
                },
            )

        async with _mock_client(handler) as client:
            with pytest.raises(RuntimeError, match="issuer mismatch"):
                await create_jwt_verifier(
                    _settings(oauth_issuer="https://idp.example.com"),
                    http_client=client,
                )
