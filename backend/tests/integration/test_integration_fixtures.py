"""Tests for the integration suite's own speed-ups.

- The suite shares one FastMCP server between every app it mounts, because
  building one registers every tool and generates its JSON schemas, which used
  to be most of each API and MCP test's setup. These tests pin what may and may
  not share it.
- Migration tests start from a template database cloned at the revision they
  first upgrade to, rather than migrating an empty database from base. These
  tests pin that the clone matches a real migration and that every later
  command still runs alembic.
"""

import copy
import logging
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

import pytest
from fastmcp import FastMCP
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette

from app.infrastructure.config import Settings
from app.main import create_app
from app.mcp.shared.read_only_tools import create_read_only_mcp_server
from tests.integration.mcp.http_helpers import call_mcp_tool
from tests.integration.migration_helpers import (
    MigrationTemplates,
    RunAlembic,
    run_alembic_subprocess,
)

LifespanClientFactory = Callable[[], AbstractAsyncContextManager[Any]]


def _mounted_mcp_server(app: Any) -> FastMCP[None]:
    mcp_app = cast(Starlette, app.state.mcp_app)
    return cast(FastMCP[None], mcp_app.state.fastmcp_server)


@pytest.fixture
def unauthenticated_settings(test_settings: Settings) -> Settings:
    """Settings that build no MCP auth provider, whatever ``.env`` configures.

    ``test_settings`` takes every field it does not name from the environment,
    so local OAuth credentials would otherwise give these apps an auth
    provider, and with it a server of their own.
    """
    return test_settings.model_copy(update={"disable_auth": True})


@pytest.fixture
def oauth_settings(test_settings: Settings) -> Settings:
    """Settings that always build an MCP auth provider (GitHub OAuth)."""
    return test_settings.model_copy(
        update={
            "disable_auth": False,
            "webhook_base_url": "https://test.example.com",
            "github_client_id": "test-github-client-id",
            "github_client_secret": "test-github-client-secret",
        }
    )


@pytest.mark.integration
class TestSharedMcpServer:
    """Mounted apps share one server; nothing else does."""

    def test_two_apps_mount_the_same_server_on_their_own_asgi_apps(
        self, unauthenticated_settings: Settings
    ) -> None:
        first = create_app(settings=unauthenticated_settings)
        second = create_app(settings=unauthenticated_settings)

        assert _mounted_mcp_server(first) is _mounted_mcp_server(second)
        assert first.state.mcp_app is not second.state.mcp_app

    def test_an_app_with_an_auth_provider_builds_its_own_server(
        self, unauthenticated_settings: Settings, oauth_settings: Settings
    ) -> None:
        shared = _mounted_mcp_server(create_app(settings=unauthenticated_settings))

        authed = _mounted_mcp_server(create_app(settings=oauth_settings))

        assert authed.auth is not None
        assert authed is not shared

    async def test_building_the_read_only_server_leaves_the_shared_schemas_alone(
        self, unauthenticated_settings: Settings
    ) -> None:
        """The read-only server sanitises its tools' schemas in place.

        It must do that to a server of its own: were it handed the shared one,
        every later test would see the sanitised schemas.
        """
        shared = _mounted_mcp_server(create_app(settings=unauthenticated_settings))
        tool = await shared.get_tool("search_journals")
        assert tool is not None
        before = copy.deepcopy(tool.parameters)

        await create_read_only_mcp_server()

        assert tool.parameters == before

    async def test_the_shared_server_serves_one_lifespan_after_another(
        self, authenticated_lifespan_client: LifespanClientFactory
    ) -> None:
        for _ in range(2):
            async with authenticated_lifespan_client() as client:
                payload = await call_mcp_tool(client, "list_journal_types", {})
                assert payload["journal_types"]


async def _schema_fingerprint(
    engine_url: str,
) -> tuple[str, frozenset[tuple[Any, ...]]]:
    """The revision and every public column's shape in the database at ``engine_url``."""
    engine = create_async_engine(engine_url)
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            columns = (
                await conn.execute(
                    text(
                        """
                        SELECT table_name, column_name, data_type, is_nullable,
                               column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        """
                    )
                )
            ).fetchall()
            return str(version), frozenset(tuple(row) for row in columns)
    finally:
        await engine.dispose()


async def _revision(engine_url: str) -> str:
    version, _ = await _schema_fingerprint(engine_url)
    return version


@pytest.fixture
def isolated_templates(throwaway_database: URL) -> Iterator[MigrationTemplates]:
    """A template registry of this test's own, so its builds are observable."""
    templates = MigrationTemplates(
        throwaway_database.set(database="postgres"),
        prefix=f"tpl_{os.getpid()}_t",
    )
    try:
        yield templates
    finally:
        templates.drop_all()


@pytest.mark.integration
@pytest.mark.slow
class TestMigrationTemplates:
    """The first upgrade of a fresh throwaway database is cloned, not migrated.

    Every later command runs real alembic, so a migration under test still runs.
    """

    async def test_a_clone_matches_a_real_migration_to_the_same_revision(
        self, throwaway_database: URL, isolated_templates: MigrationTemplates
    ) -> None:
        real_url = throwaway_database.render_as_string(hide_password=False)
        run_alembic_subprocess(real_url, "upgrade", "0134")
        cloned_name = f"{throwaway_database.database}_c"
        cloned_url = throwaway_database.set(database=cloned_name).render_as_string(
            hide_password=False
        )

        isolated_templates.clone_into(cloned_name, "0134")
        try:
            assert await _schema_fingerprint(cloned_url) == (
                await _schema_fingerprint(real_url)
            )
        finally:
            isolated_templates.drop_database(cloned_name)

    def test_revisions_resolve_whatever_the_working_directory(
        self,
        throwaway_database: URL,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``alembic.ini`` names its scripts relative to the working directory."""
        monkeypatch.chdir(tmp_path)

        templates = MigrationTemplates(
            throwaway_database.set(database="postgres"),
            prefix=f"tpl_{os.getpid()}_cwd",
        )

        assert templates.template_name("head").startswith(f"tpl_{os.getpid()}_cwd_")

    def test_a_later_revision_is_built_from_the_nearest_template(
        self, throwaway_database: URL, isolated_templates: MigrationTemplates
    ) -> None:
        name = str(throwaway_database.database)

        isolated_templates.clone_into(name, "0133")
        isolated_templates.clone_into(name, "0135")

        assert isolated_templates.template_source("0133") is None
        assert isolated_templates.template_source("0135") == (
            isolated_templates.template_name("0133")
        )

    async def test_the_first_upgrade_of_a_fresh_database_is_a_clone(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        migration_templates: MigrationTemplates,
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        clones = migration_templates.clones

        run_alembic(url, "upgrade", "0133")

        assert migration_templates.clones == clones + 1
        assert await _revision(url) == "0133"

    async def test_a_second_command_runs_real_alembic(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        migration_templates: MigrationTemplates,
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0133")
        clones = migration_templates.clones

        output = run_alembic(url, "upgrade", "0134")

        assert migration_templates.clones == clones
        assert "Running upgrade 0133 -> 0134" in output
        assert await _revision(url) == "0134"

    async def test_a_first_upgrade_with_x_args_runs_real_alembic(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        migration_templates: MigrationTemplates,
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        clones = migration_templates.clones

        output = run_alembic(url, "upgrade", "0002", x_args={"unused": "value"})

        assert migration_templates.clones == clones
        assert "Running upgrade 0001 -> 0002" in output
        assert await _revision(url) == "0002"


def _no_subprocess(*args: object, **kwargs: object) -> None:
    raise AssertionError("alembic ran in a subprocess")


@pytest.mark.integration
@pytest.mark.slow
class TestInProcessAlembic:
    """``run_alembic`` runs alembic inside the test process.

    Starting an interpreter and importing the app cost about a second per
    command; in-process it must still target the right database, return the
    CLI's log lines and leave the session's logging as it found it.
    """

    async def test_run_alembic_runs_in_process(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0133")
        monkeypatch.setattr("subprocess.run", _no_subprocess)

        output = run_alembic(url, "upgrade", "0134")

        assert "Running upgrade 0133 -> 0134" in output
        assert await _revision(url) == "0134"

    async def test_the_url_passed_in_wins_over_database_url(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fixtures point ``DATABASE_URL`` at the shared session database."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0133")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql://nobody:nothing@127.0.0.1:1/nowhere"
        )

        run_alembic(url, "upgrade", "0134")

        assert await _revision(url) == "0134"

    async def test_logging_survives_an_in_process_migration(
        self,
        throwaway_database: URL,
        run_alembic: RunAlembic,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``alembic.ini``'s ``fileConfig`` would disable every existing logger."""
        probe = logging.getLogger("app.in_process_alembic_probe")
        alembic_logger = logging.getLogger("alembic")
        before = (
            alembic_logger.level,
            list(alembic_logger.handlers),
            alembic_logger.propagate,
        )
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0133")

        run_alembic(url, "upgrade", "0134")

        assert not probe.disabled
        with caplog.at_level(logging.WARNING, logger=probe.name):
            probe.warning("still logging")
        assert [r.getMessage() for r in caplog.records if r.name == probe.name] == [
            "still logging"
        ]
        assert (
            alembic_logger.level,
            list(alembic_logger.handlers),
            alembic_logger.propagate,
        ) == before

    async def test_the_alembic_cli_still_migrates(
        self, throwaway_database: URL, run_alembic: RunAlembic
    ) -> None:
        """The path operators use: a real ``python -m alembic`` subprocess."""
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", "0133")

        output = run_alembic_subprocess(url, "upgrade", "0134")

        assert "Running upgrade 0133 -> 0134" in output
        assert await _revision(url) == "0134"
