"""Unit tests for SSE integration-test helpers."""

from types import SimpleNamespace

from tests.integration.sse_helpers import reset_sse_starlette_appstatus_event


class TestResetSseStarletteAppstatusEvent:
    """Test reset of sse-starlette's leaked global shutdown event."""

    def test_resets_should_exit_event_when_appstatus_exists(self, monkeypatch) -> None:
        """It should clear the leaked event for subsequent lifespan-managed tests."""
        app_status = SimpleNamespace(should_exit_event=object())
        fake_module = SimpleNamespace(AppStatus=app_status)

        monkeypatch.setattr(
            "tests.integration.sse_helpers.import_module",
            lambda name: fake_module,
        )

        reset_sse_starlette_appstatus_event()

        assert app_status.should_exit_event is None

    def test_noops_when_sse_starlette_is_unavailable(self, monkeypatch) -> None:
        """It should quietly no-op when sse-starlette is not installed."""

        def raise_module_not_found(_: str) -> SimpleNamespace:
            raise ModuleNotFoundError

        monkeypatch.setattr(
            "tests.integration.sse_helpers.import_module",
            raise_module_not_found,
        )

        reset_sse_starlette_appstatus_event()
