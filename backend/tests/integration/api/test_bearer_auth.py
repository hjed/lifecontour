"""Integration tests for direct OAuth bearer-token authentication.

Exercises the real :class:`AuthProvider` against a minimal app with a test
JWT verifier backed by an in-test RSA keypair (no network / real IdP).
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import (
    FastapiProvider,
    FromDishka,
    inject,
    setup_dishka,
)
from fastapi import FastAPI
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.middleware.sessions import SessionMiddleware

from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AdminAccess, AuthProvider
from tests.integration.conftest import _create_session_cookie_value

ISSUER = "https://idp.test.example.com"
AUDIENCE = "pms-api"
SESSION_SECRET = "test-session-secret"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def key_pair() -> RSAKeyPair:
    return RSAKeyPair.generate()


def _make_token(
    key_pair: RSAKeyPair,
    *,
    scopes: list[str] | None = None,
    subject: str = "user-1",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    email: str = "user@example.com",
) -> str:
    return key_pair.create_token(
        subject=subject,
        issuer=issuer,
        audience=audience,
        scopes=scopes,
        additional_claims={"email": email, "name": "Test User"},
    )


def _build_settings(*, enforce_scopes: bool = True) -> Settings:
    return Settings(
        oauth_issuer=ISSUER,
        oauth_audience=AUDIENCE,
        oauth_enforce_scopes=enforce_scopes,
        session_secret_key=SESSION_SECRET,
        disable_auth=False,
    )


@asynccontextmanager
async def _client(
    key_pair: RSAKeyPair,
    *,
    enforce_scopes: bool = True,
) -> AsyncGenerator[AsyncClient]:
    settings = _build_settings(enforce_scopes=enforce_scopes)
    verifier = JWTVerifier(
        public_key=key_pair.public_key,
        issuer=ISSUER,
        audience=AUDIENCE,
    )

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

    @app.get("/whoami")
    @inject
    async def whoami(user: FromDishka[SessionUser]) -> dict[str, str]:
        return {"id": user.id, "email": user.email, "provider": user.provider}

    @app.post("/whoami")
    @inject
    async def whoami_write(user: FromDishka[SessionUser]) -> dict[str, str]:
        return {"id": user.id}

    @app.post("/admin-action")
    @inject
    async def admin_action(
        user: FromDishka[SessionUser], _admin: FromDishka[AdminAccess]
    ) -> dict[str, str]:
        return {"id": user.id}

    @app.get("/maybe")
    @inject
    async def maybe(user: FromDishka[SessionUser | None]) -> dict[str, Any]:
        return {"id": user.id if user else None}

    class TestConnectionProvider(Provider):
        # Satisfies the DI graph (GoogleTokenService) but is never resolved by
        # these auth-only routes.
        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return cast(AsyncConnection, object())

    class TestConfigProvider(Provider):
        @provide(scope=Scope.APP)
        def get_settings(self) -> Settings:
            return settings

        @provide(scope=Scope.APP)
        def get_verifier(self) -> JWTVerifier | None:
            return verifier

    container = make_async_container(
        TestConnectionProvider(),
        AuthProvider(),
        # Listed after AuthProvider so the static test verifier overrides
        # AuthProvider.get_jwt_verifier (which would attempt network discovery).
        TestConfigProvider(),
        FastapiProvider(),
    )
    setup_dishka(container, app)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await container.close()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client_factory(key_pair: RSAKeyPair) -> Callable[..., Any]:
    def factory(*, enforce_scopes: bool = True) -> Any:
        return _client(key_pair, enforce_scopes=enforce_scopes)

    return factory


class TestBearerHappyPath:
    async def test_read_token_allows_get(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:read"])
        async with client_factory() as client:
            resp = await client.get("/whoami", headers=_bearer(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "user-1"
        assert body["email"] == "user@example.com"
        assert body["provider"] == "oauth-token"

    async def test_write_token_allows_get_and_post(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:write"])
        async with client_factory() as client:
            get_resp = await client.get("/whoami", headers=_bearer(token))
            post_resp = await client.post("/whoami", headers=_bearer(token))
        assert get_resp.status_code == 200
        assert post_resp.status_code == 200

    async def test_admin_token_allows_admin_action(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:admin"])
        async with client_factory() as client:
            resp = await client.post("/admin-action", headers=_bearer(token))
        assert resp.status_code == 200


class TestScopeEnforcement:
    async def test_read_token_forbidden_on_post(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:read"])
        async with client_factory() as client:
            resp = await client.post("/whoami", headers=_bearer(token))
        assert resp.status_code == 403
        assert "pms:write" in resp.json()["detail"]

    async def test_write_token_forbidden_on_admin(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:write"])
        async with client_factory() as client:
            resp = await client.post("/admin-action", headers=_bearer(token))
        assert resp.status_code == 403
        assert "pms:admin" in resp.json()["detail"]

    async def test_token_without_pms_scopes_accepted_as_full(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        # No recognized pms:* scope -> accept-any fallback grants full access.
        token = _make_token(key_pair, scopes=["openid", "profile"])
        async with client_factory() as client:
            post_resp = await client.post("/whoami", headers=_bearer(token))
            admin_resp = await client.post("/admin-action", headers=_bearer(token))
        assert post_resp.status_code == 200
        assert admin_resp.status_code == 200

    async def test_enforcement_off_ignores_scopes(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:read"])
        async with client_factory(enforce_scopes=False) as client:
            resp = await client.post("/admin-action", headers=_bearer(token))
        assert resp.status_code == 200


class TestInvalidTokens:
    async def test_garbage_token_unauthorized(
        self, client_factory: Callable[..., Any]
    ) -> None:
        async with client_factory() as client:
            resp = await client.get("/whoami", headers=_bearer("not-a-jwt"))
        assert resp.status_code == 401

    async def test_wrong_audience_unauthorized(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:read"], audience="other-api")
        async with client_factory() as client:
            resp = await client.get("/whoami", headers=_bearer(token))
        assert resp.status_code == 401

    async def test_wrong_issuer_unauthorized(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(
            key_pair, scopes=["pms:read"], issuer="https://evil.example.com"
        )
        async with client_factory() as client:
            resp = await client.get("/whoami", headers=_bearer(token))
        assert resp.status_code == 401

    async def test_no_credentials_unauthorized(
        self, client_factory: Callable[..., Any]
    ) -> None:
        async with client_factory() as client:
            resp = await client.get("/whoami")
        assert resp.status_code == 401


class TestSessionFallback:
    async def test_session_cookie_still_works(
        self, client_factory: Callable[..., Any]
    ) -> None:
        user = SessionUser(
            id="session-user", email="s@example.com", name="S", provider="github"
        )
        cookie = _create_session_cookie_value(
            {"user": user.model_dump(mode="json")}, SESSION_SECRET
        )
        async with client_factory() as client:
            client.cookies.set("session", cookie)
            resp = await client.get("/whoami")
        assert resp.status_code == 200
        assert resp.json()["id"] == "session-user"

    async def test_optional_user_anonymous_without_credentials(
        self, client_factory: Callable[..., Any]
    ) -> None:
        async with client_factory() as client:
            resp = await client.get("/maybe")
        assert resp.status_code == 200
        assert resp.json()["id"] is None

    async def test_optional_user_resolves_bearer(
        self, client_factory: Callable[..., Any], key_pair: RSAKeyPair
    ) -> None:
        token = _make_token(key_pair, scopes=["pms:read"])
        async with client_factory() as client:
            resp = await client.get("/maybe", headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["id"] == "user-1"
