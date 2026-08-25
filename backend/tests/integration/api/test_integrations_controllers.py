"""
Integration tests for integrations API controllers.

Tests the real API endpoints with actual services and database connections.
Uses the established authentication pattern from other integration tests.
"""

from contextlib import suppress
from unittest.mock import patch

import anyio
import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.exceptions import JobNotFoundException
from app.infrastructure.auth.google_token_service import GoogleTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
from app.infrastructure.di.settings import SettingsProvider
from app.infrastructure.di.tasks import TaskProvider
from app.main import create_app


class TestIntegrationsControllers:
    """Integration tests for integrations API controllers."""

    @pytest.fixture
    def test_user(self) -> SessionUser:
        """Create a test user."""
        return SessionUser(
            id="123",
            email="test@example.com",
            name="Test User",
            provider="test",
        )

    @pytest.fixture
    def client(self, test_settings, test_user, async_connection):
        """Create authenticated test client with all necessary providers."""

        class TestAuthProvider(Provider):
            """Test provider for authenticated client."""

            @provide(scope=Scope.APP)
            def get_settings(self) -> Settings:
                """Provide test settings to all providers."""
                return test_settings  # type: ignore

            @provide(scope=Scope.REQUEST)
            def get_session_user(self) -> SessionUser:
                return test_user  # type: ignore

            @provide(scope=Scope.REQUEST)
            def get_oauth_service(self, settings: Settings) -> OAuthService:
                return OAuthService(settings)

            @provide(scope=Scope.REQUEST)
            def get_google_token_service(
                self, connection: AsyncConnection, settings: Settings
            ) -> GoogleTokenService:
                """Get Google Token service instance for request scope."""
                return GoogleTokenService(
                    connection=connection,
                    encryption_key=settings.google_encryption_key
                    or "EQbCaxDnFZZ4_mrcOMbMPmgz9-NDcv3ZfxxmzPu0j0s=",
                )

        # Create app with test settings
        app = create_app(settings=test_settings)

        class TestDatabaseProvider(Provider):
            def __init__(self, connection: AsyncConnection):
                super().__init__()
                self.connection = connection

            @provide(scope=Scope.REQUEST)
            def get_connection(self) -> AsyncConnection:
                return self.connection

        # Replace container with test container that includes all providers
        test_container = make_async_container(
            TestDatabaseProvider(async_connection),
            InfrastructureProvider(),
            TestAuthProvider(),  # Override auth with test user and provide settings
            ContactProvider(),
            JournalProvider(),
            TaskProvider(),
            SettingsProvider(),
            IntegrationProvider(),
            FastapiProvider(),
        )

        # Ensure any existing Dishka container is closed cleanly (Dishka containers are async).
        existing_container = getattr(app.state, "dishka_container", None)
        if existing_container is not None:
            with suppress(Exception):
                anyio.run(existing_container.close)
        app.state.dishka_container = test_container
        setup_dishka(test_container, app)

        # Use a yield fixture so we can reliably close the async container and avoid
        # resource warnings about un-awaited coroutines.
        with TestClient(app) as test_client:
            yield test_client

        with suppress(Exception):
            anyio.run(test_container.close)

    def test_trigger_google_sync_success(self, client: TestClient):
        """Test successful Google Contacts sync trigger."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_google_account_email,
            patch(
                "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_sync"
            ) as mock_enqueue,
            patch(
                "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details"
            ) as mock_get_details,
        ):
            mock_get_google_account_email.return_value = "connected@gmail.com"
            # Mock successful job enqueueing
            mock_enqueue.return_value = "test-job-123"
            mock_get_details.return_value = {
                "job_id": "test-job-123",
                "status": "queued",
                "sync_type": "smart",
                "created_at": "2024-01-01T10:00:00Z",
                "started_at": None,
                "completed_at": None,
                "error_message": None,
                "contacts_processed": None,
                "contacts_created": None,
                "contacts_updated": None,
                "contacts_deleted": None,
                "progress": None,
            }

            # Make request with proper body
            response = client.post(
                "/api/integrations/google/contacts/sync", json={"sync_type": "smart"}
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["id"] == "test-job-123"
            assert data["data"]["type"] == "sync-job"
            attributes = data["data"]["attributes"]
            assert attributes["status"] == "queued"
            assert attributes["syncType"] == "smart"

            # Verify service was called
            mock_enqueue.assert_called_once_with(
                google_account_email="connected@gmail.com",
                user_id="123",
                sync_type="smart",
            )
            mock_get_details.assert_called_once_with(
                job_id="test-job-123", user_id="123"
            )

    def test_trigger_google_sync_requires_connected_google_account(
        self, client: TestClient
    ):
        """Test sync trigger fails early when the user has no connected Google account."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_google_account_email,
            patch(
                "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_sync"
            ) as mock_enqueue,
        ):
            mock_get_google_account_email.side_effect = ValueError(
                "No Google Contacts connection found for user 123"
            )

            response = client.post(
                "/api/integrations/google/contacts/sync", json={"sync_type": "smart"}
            )

            assert response.status_code == 400
            data = response.json()
            assert (
                data["errors"][0]["detail"]
                == "Invalid sync parameters: No Google Contacts connection found for user 123"
            )
            mock_enqueue.assert_not_called()

    def test_trigger_google_sync_failure(self, client: TestClient):
        """Test Google Contacts sync trigger failure."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_google_account_email,
            patch(
                "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_sync"
            ) as mock_enqueue,
        ):
            mock_get_google_account_email.return_value = "connected@gmail.com"
            # Mock job enqueueing failure
            mock_enqueue.side_effect = Exception("Redis connection failed")

            # Make request with proper body
            response = client.post(
                "/api/integrations/google/contacts/sync", json={"sync_type": "smart"}
            )

            # Verify error response
            assert response.status_code == 500
            data = response.json()
            assert (
                data["errors"][0]["detail"]
                == "An unexpected error occurred while queueing the sync job"
            )

    def test_get_sync_job_status_success(self, client: TestClient):
        """Test successful job status retrieval."""
        job_id = "test-job-456"

        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details"
        ) as mock_get_details:
            mock_get_details.return_value = {
                "job_id": job_id,
                "status": "completed",
                "sync_type": "smart",
                "created_at": "2024-01-01T10:00:00Z",
                "started_at": "2024-01-01T10:00:10Z",
                "completed_at": "2024-01-01T10:05:00Z",
                "error_message": None,
                "contacts_processed": 5,
                "contacts_created": 1,
                "contacts_updated": 2,
                "contacts_deleted": 0,
                "progress": 100,
            }

            # Make request
            response = client.get(f"/api/integrations/google/contacts/sync/{job_id}")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["id"] == job_id
            assert data["data"]["type"] == "sync-job"
            attributes = data["data"]["attributes"]
            assert attributes["status"] == "completed"
            assert attributes["contactsProcessed"] == 5

            # Verify service was called with job_id and user_id (user.id is a string)
            mock_get_details.assert_called_once_with(job_id=job_id, user_id="123")

    def test_get_sync_job_status_failure(self, client: TestClient):
        """Test job status retrieval failure."""
        job_id = "test-job-789"

        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_sync_job_details"
        ) as mock_get_details:
            mock_get_details.side_effect = JobNotFoundException("Job not found")

            # Make request
            response = client.get(f"/api/integrations/google/contacts/sync/{job_id}")

            # Verify error response (404 for job not found is correct)
            assert response.status_code == 404
            data = response.json()
            assert data["errors"][0]["detail"] == "Job not found"

    def test_get_integrations_health_success(self, client: TestClient):
        """Test successful health check."""
        with patch(
            "app.core.integrations.health_service.IntegrationHealthService.get_overall_health"
        ) as mock_health:
            # Mock successful health check
            mock_health.return_value = {
                "status": "healthy",
                "timestamp": "2024-01-01T10:00:00Z",
                "services": {
                    "redis": {
                        "status": "healthy",
                        "response_time_ms": 2.5,
                        "queue_length": 0,
                    },
                    "google_worker": {
                        "status": "healthy",
                        "recent_jobs": 0,
                        "worker_version": "1.0.0",
                    },
                    "google_api": {
                        "status": "healthy",
                        "rate_limit_remaining": "90%",
                    },
                },
                "version": "1.0.0",
            }

            # Make request
            response = client.get("/api/integrations/health")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["id"] == "health"
            assert data["data"]["type"] == "integration-health"

            attributes = data["data"]["attributes"]
            assert attributes["overall"] == "healthy"
            assert attributes["redis"]["status"] == "healthy"
            assert attributes["worker"]["status"] == "healthy"

            # Verify service was called
            mock_health.assert_called_once()

    def test_get_integrations_health_unhealthy(self, client: TestClient):
        """Test health check when services are unhealthy."""
        with patch(
            "app.core.integrations.health_service.IntegrationHealthService.get_overall_health"
        ) as mock_health:
            # Mock unhealthy health check
            mock_health.return_value = {
                "status": "unhealthy",
                "timestamp": "2024-01-01T10:00:00Z",
                "services": {
                    "redis": {
                        "status": "unhealthy",
                        "error": "Connection refused",
                    },
                    "google_worker": {
                        "status": "unhealthy",
                        "error": "Worker not responding",
                    },
                    "google_api": {
                        "status": "healthy",
                        "rate_limit_remaining": "90%",
                    },
                },
                "version": "1.0.0",
            }

            # Make request
            response = client.get("/api/integrations/health")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            attributes = data["data"]["attributes"]
            assert attributes["overall"] == "unhealthy"
            assert attributes["redis"]["status"] == "unhealthy"
            assert attributes["worker"]["status"] == "unhealthy"

    def test_get_integrations_health_service_exception(self, client: TestClient):
        """Test health check when health service raises exception."""
        with patch(
            "app.core.integrations.health_service.IntegrationHealthService.get_overall_health"
        ) as mock_health:
            # Mock health service exception
            mock_health.side_effect = Exception("Health service failed")

            # Make request
            response = client.get("/api/integrations/health")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            attributes = data["data"]["attributes"]
            assert attributes["overall"] == "unhealthy"
            assert attributes["redis"]["status"] == "unhealthy"
            assert "Health service failed" in (
                attributes["redis"]["errorMessage"] or ""
            )

    def test_get_google_status_disconnected(self, client: TestClient):
        """Test Google Contacts status endpoint returns disconnected state."""
        # Make request
        response = client.get("/api/integrations/google/contacts/status")

        # Verify JSON API response format
        assert response.status_code == 200
        data = response.json()

        # Verify JSON API structure
        assert "data" in data
        assert data["data"]["id"] == "google"
        assert data["data"]["type"] == "integration-status"

        # Verify attributes (using camelCase as per JSON API)
        attributes = data["data"]["attributes"]
        assert attributes["connected"] is False
        assert attributes["status"] == "disconnected"
        assert attributes["syncCount"] == 0
        assert attributes["lastSync"] is None

    # OAuth Integration Tests
    def test_google_oauth_authorize_uses_frontend_url_for_callback(
        self, client: TestClient, test_settings
    ):
        """Test that OAuth authorize uses settings.frontend_url, not request.base_url.

        Behind a reverse proxy, request.base_url reflects the internal HTTP
        scheme (http://) while settings.frontend_url has the correct external
        URL (https://). This test verifies the controller passes the correct
        callback URL to the OAuth service.
        """
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_google_authorization_url"
        ) as mock_auth_url:
            mock_auth_url.return_value = "https://accounts.google.com/oauth/authorize?client_id=test&redirect_uri=test&scope=contacts&state=test_state_123"

            client.post(
                "/api/integrations/google/contacts/oauth/authorize",
                json={"redirect_url": "/integrations"},
            )

            # Verify the callback URL uses settings.frontend_url
            call_args = mock_auth_url.call_args
            callback_url = call_args[0][1]  # second positional arg: redirect_uri
            expected_callback = f"{test_settings.frontend_url}/auth/callback"
            assert callback_url == expected_callback, (
                f"Expected callback URL from settings.frontend_url ({expected_callback}), "
                f"got {callback_url}"
            )

    def test_google_oauth_callback_uses_frontend_url_for_redirect(
        self, client: TestClient, test_settings
    ):
        """Test that OAuth callback uses settings.frontend_url, not request.base_url."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.handle_google_callback"
            ) as mock_callback,
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_google_user_email"
            ) as mock_get_email,
            patch(
                "app.infrastructure.auth.google_token_service.GoogleTokenService.store_tokens"
            ) as _mock_store_tokens,
        ):
            mock_callback.return_value = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
            }
            mock_get_email.return_value = "test@gmail.com"

            client.post(
                "/api/integrations/google/contacts/oauth/callback",
                json={"code": "test_auth_code", "state": "test_state"},
            )

            # Verify the callback URL uses settings.frontend_url
            call_args = mock_callback.call_args
            callback_url = call_args[0][3]  # fourth positional arg: redirect_uri
            expected_callback = f"{test_settings.frontend_url}/auth/callback"
            assert callback_url == expected_callback, (
                f"Expected callback URL from settings.frontend_url ({expected_callback}), "
                f"got {callback_url}"
            )

    def test_google_oauth_authorize_success(self, client: TestClient):
        """Test successful Google Contacts OAuth authorization initiation."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_google_authorization_url"
        ) as mock_auth_url:
            # Mock successful authorization URL generation with state parameter
            mock_auth_url.return_value = "https://accounts.google.com/oauth/authorize?client_id=test&redirect_uri=test&scope=contacts&state=test_state_123"

            # Make request
            response = client.post(
                "/api/integrations/google/contacts/oauth/authorize",
                json={"redirect_url": "/integrations"},
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert "authorization_url" in data
            assert "state" in data
            assert data["authorization_url"].startswith(
                "https://accounts.google.com/oauth/authorize"
            )
            assert data["state"] == "test_state_123"

            # Verify service was called
            mock_auth_url.assert_called_once()

    def test_google_oauth_authorize_missing_provider(self, client: TestClient):
        """Test OAuth authorization when Google provider is not configured."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_google_authorization_url"
        ) as mock_auth_url:
            # Mock provider not configured error
            from fastapi import HTTPException

            mock_auth_url.side_effect = HTTPException(
                status_code=400, detail="Google OAuth provider not configured"
            )

            # Make request
            response = client.post(
                "/api/integrations/google/contacts/oauth/authorize",
                json={"redirect_url": "/integrations"},
            )

            # Verify error response (JSON API format)
            assert response.status_code == 400
            data = response.json()
            assert "errors" in data
            assert len(data["errors"]) > 0
            assert "Google OAuth provider not configured" in data["errors"][0]["detail"]

    def test_google_oauth_callback_success(self, client: TestClient):
        """Test successful Google Contacts OAuth callback."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.handle_google_callback"
            ) as mock_callback,
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_google_user_email"
            ) as mock_get_email,
            patch(
                "app.infrastructure.auth.google_token_service.GoogleTokenService.store_tokens"
            ) as mock_store_tokens,
        ):
            # Mock successful callback handling
            mock_callback.return_value = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
            }
            mock_get_email.return_value = "test@gmail.com"

            # Make request
            response = client.post(
                "/api/integrations/google/contacts/oauth/callback",
                json={"code": "test_auth_code", "state": "test_state"},
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "Google Contacts connected successfully" in data["message"]
            assert data["redirect_url"] == "/integrations"

            # Verify services were called
            mock_callback.assert_called_once()
            mock_get_email.assert_called_once_with("test_access_token")
            mock_store_tokens.assert_called_once()

    def test_google_oauth_callback_invalid_code(self, client: TestClient):
        """Test OAuth callback with invalid authorization code."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.handle_google_callback"
        ) as mock_callback:
            # Mock invalid code error
            mock_callback.side_effect = ValueError("Invalid authorization code")

            # Make request
            response = client.post(
                "/api/integrations/google/contacts/oauth/callback",
                json={"code": "invalid_code", "state": "test_state"},
            )

            # Verify error response (JSON API format)
            assert response.status_code == 400
            data = response.json()
            assert "errors" in data
            assert len(data["errors"]) > 0
            assert "Invalid authorization code" in data["errors"][0]["detail"]

    def test_google_oauth_disconnect_success(self, client: TestClient):
        """Test Google Contacts OAuth disconnect successfully deletes tokens."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.disconnect_google"
        ) as mock_disconnect:
            # Mock successful disconnect (returns True)
            mock_disconnect.return_value = True

            # Make request
            response = client.delete(
                "/api/integrations/google/contacts/oauth/disconnect"
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "disconnected successfully" in data["message"]

            # Verify service was called
            mock_disconnect.assert_called_once()

    def test_google_oauth_disconnect_no_tokens(self, client: TestClient):
        """Test Google Contacts OAuth disconnect when no tokens exist."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.disconnect_google"
        ) as mock_disconnect:
            # Mock no tokens found (returns False)
            mock_disconnect.return_value = False

            # Make request
            response = client.delete(
                "/api/integrations/google/contacts/oauth/disconnect"
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "No Google Contacts connection found" in data["message"]

            # Verify service was called
            mock_disconnect.assert_called_once()

    # Google Calendar List Tests
    def test_list_google_calendars_success(self, client: TestClient):
        """Test successful Google Calendar list retrieval."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_email,
            patch(
                "app.infrastructure.auth.google_token_service.GoogleTokenService.get_tokens"
            ) as mock_get_tokens,
            patch(
                "app.api.integrations.controllers.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_get_email.return_value = "user@gmail.com"
            mock_get_tokens.return_value = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "is_expired": False,
            }

            # Mock the aiohttp response
            from unittest.mock import AsyncMock, MagicMock

            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={
                    "items": [
                        {
                            "id": "primary@gmail.com",
                            "summary": "My Calendar",
                            "description": "Main calendar",
                            "backgroundColor": "#4285f4",
                            "primary": True,
                        },
                        {
                            "id": "work@group.v.calendar.google.com",
                            "summary": "Work",
                            "backgroundColor": "#7986cb",
                            "primary": False,
                        },
                    ]
                }
            )

            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_context)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            response = client.get("/api/integrations/google/calendars")

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) == 2

            # Verify first calendar (primary)
            cal1 = data["data"][0]
            assert cal1["id"] == "primary@gmail.com"
            assert cal1["type"] == "google-calendar"
            assert cal1["attributes"]["summary"] == "My Calendar"
            assert cal1["attributes"]["primary"] is True
            assert cal1["attributes"]["backgroundColor"] == "#4285f4"

            # Verify second calendar
            cal2 = data["data"][1]
            assert cal2["id"] == "work@group.v.calendar.google.com"
            assert cal2["attributes"]["summary"] == "Work"
            assert cal2["attributes"]["primary"] is False

    def test_list_google_calendars_api_error(self, client: TestClient):
        """Test Google Calendar list when Google API returns an error."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_email,
            patch(
                "app.infrastructure.auth.google_token_service.GoogleTokenService.get_tokens"
            ) as mock_get_tokens,
            patch(
                "app.api.integrations.controllers.aiohttp.ClientSession"
            ) as mock_session_cls,
        ):
            mock_get_email.return_value = "user@gmail.com"
            mock_get_tokens.return_value = {
                "access_token": "expired_token",
                "refresh_token": "test_refresh_token",
                "is_expired": True,
            }

            from unittest.mock import AsyncMock, MagicMock

            mock_response = AsyncMock()
            mock_response.status = 401
            mock_response.text = AsyncMock(return_value="Unauthorized")

            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_response)
            mock_context.__aexit__ = AsyncMock(return_value=False)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_context)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            response = client.get("/api/integrations/google/calendars")

            assert response.status_code == 502
            data = response.json()
            assert "errors" in data
            assert "Failed to fetch Google Calendars" in data["errors"][0]["detail"]

    def test_list_google_calendars_no_google_account(self, client: TestClient):
        """Test Google Calendar list when user has no Google account connected."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
        ) as mock_get_email:
            mock_get_email.side_effect = ValueError(
                "No Google Contacts connection found for user 123"
            )

            response = client.get("/api/integrations/google/calendars")

            assert response.status_code == 401
            data = response.json()
            assert "errors" in data
            assert "Google account not connected" in data["errors"][0]["detail"]

    def test_list_google_calendars_no_tokens(self, client: TestClient):
        """Test Google Calendar list when tokens are not found."""
        from app.infrastructure.auth.google_token_service import (
            GoogleTokenNotFoundError,
        )

        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.get_connected_google_account_email"
            ) as mock_get_email,
            patch(
                "app.infrastructure.auth.google_token_service.GoogleTokenService.get_tokens"
            ) as mock_get_tokens,
        ):
            mock_get_email.return_value = "user@gmail.com"
            mock_get_tokens.side_effect = GoogleTokenNotFoundError(
                "No Google tokens found"
            )

            response = client.get("/api/integrations/google/calendars")

            assert response.status_code == 401
            data = response.json()
            assert "errors" in data
            assert "Google tokens not found" in data["errors"][0]["detail"]
