"""
Integration tests for integrations API controllers.

Tests the real API endpoints with actual services and database connections.
Uses the established authentication pattern from other integration tests.
"""

from unittest.mock import patch

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.google_token_service import GoogleTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings
from app.infrastructure.di.contacts import ContactProvider
from app.infrastructure.di.database import DatabaseProvider
from app.infrastructure.di.infrastructure import InfrastructureProvider
from app.infrastructure.di.integrations import IntegrationProvider
from app.infrastructure.di.journal import JournalProvider
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
    def client(self, test_settings, test_user):
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

        # Replace container with test container that includes all providers
        test_container = make_async_container(
            DatabaseProvider(test_settings),
            InfrastructureProvider(),
            TestAuthProvider(),  # Override auth with test user and provide settings
            ContactProvider(),
            JournalProvider(),
            IntegrationProvider(),
            FastapiProvider(),
        )

        try:
            app.state.dishka_container.close()
        except (RuntimeError, AttributeError):
            pass
        app.state.dishka_container = test_container
        setup_dishka(test_container, app)

        return TestClient(app)

    def test_trigger_google_contacts_sync_success(self, client: TestClient):
        """Test successful Google Contacts sync trigger."""
        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_contacts_sync"
        ) as mock_enqueue:
            # Mock successful job enqueueing
            mock_enqueue.return_value = "test-job-123"

            # Make request with proper body
            response = client.post(
                "/api/integrations/google/contacts/sync", json={"sync_type": "smart"}
            )

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-123"
            assert data["status"] == "queued"
            assert "Google Contacts sync job has been queued" in data["message"]

            # Verify service was called
            mock_enqueue.assert_called_once()

    def test_trigger_google_contacts_sync_failure(self, client: TestClient):
        """Test Google Contacts sync trigger failure."""
        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.enqueue_google_contacts_sync"
        ) as mock_enqueue:
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
            "app.core.integrations.task_queue_service.TaskQueueService.get_job_status"
        ) as mock_get_status:
            # Mock successful status retrieval
            mock_get_status.return_value = {
                "job_id": job_id,
                "status": "completed",
                "message": "Job completed successfully",
                "created_at": "2024-01-01T10:00:00Z",
                "completed_at": "2024-01-01T10:05:00Z",
                "result": {"contacts_processed": 5},
            }

            # Make request
            response = client.get(f"/api/integrations/google/contacts/sync/{job_id}")

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job_id
            assert data["status"] == "completed"
            assert data["message"] == "Job completed successfully"

            # Verify service was called with job_id and user_id (user.id is a string)
            mock_get_status.assert_called_once_with(job_id, "123")

    def test_get_sync_job_status_failure(self, client: TestClient):
        """Test job status retrieval failure."""
        job_id = "test-job-789"

        with patch(
            "app.core.integrations.task_queue_service.TaskQueueService.get_job_status"
        ) as mock_get_status:
            # Mock status retrieval failure
            mock_get_status.side_effect = Exception("Job not found")

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
                    "google_contacts_worker": {
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
            assert data["status"] == "healthy"
            assert "services" in data
            assert data["services"]["redis"]["status"] == "healthy"
            assert data["services"]["google_contacts_worker"]["status"] == "healthy"
            assert data["services"]["google_api"]["status"] == "healthy"

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
                    "google_contacts_worker": {
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
            assert data["status"] == "unhealthy"
            assert data["services"]["redis"]["status"] == "unhealthy"
            assert data["services"]["google_contacts_worker"]["status"] == "unhealthy"
            assert data["services"]["google_api"]["status"] == "healthy"

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
            assert data["status"] == "unhealthy"
            assert "services" in data
            assert "error" in data["services"]
            assert "Health service failed" in data["services"]["error"]["message"]

    def test_get_google_contacts_status_disconnected(self, client: TestClient):
        """Test Google Contacts status endpoint returns disconnected state."""
        # Make request
        response = client.get("/api/integrations/google/contacts/status")

        # Verify JSON API response format
        assert response.status_code == 200
        data = response.json()

        # Verify JSON API structure
        assert "data" in data
        assert data["data"]["id"] == "google-contacts"
        assert data["data"]["type"] == "integration-status"

        # Verify attributes (using camelCase as per JSON API)
        attributes = data["data"]["attributes"]
        assert attributes["connected"] is False
        assert attributes["status"] == "disconnected"
        assert attributes["syncCount"] == 0
        assert attributes["lastSync"] is None

    # OAuth Integration Tests
    def test_google_contacts_oauth_authorize_success(self, client: TestClient):
        """Test successful Google Contacts OAuth authorization initiation."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_google_contacts_authorization_url"
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

    def test_google_contacts_oauth_authorize_missing_provider(self, client: TestClient):
        """Test OAuth authorization when Google provider is not configured."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.get_google_contacts_authorization_url"
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

    def test_google_contacts_oauth_callback_success(self, client: TestClient):
        """Test successful Google Contacts OAuth callback."""
        with (
            patch(
                "app.infrastructure.auth.oauth_service.OAuthService.handle_google_contacts_callback"
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

    def test_google_contacts_oauth_callback_invalid_code(self, client: TestClient):
        """Test OAuth callback with invalid authorization code."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.handle_google_contacts_callback"
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

    def test_google_contacts_oauth_disconnect_success(self, client: TestClient):
        """Test Google Contacts OAuth disconnect successfully deletes tokens."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.disconnect_google_contacts"
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

    def test_google_contacts_oauth_disconnect_no_tokens(self, client: TestClient):
        """Test Google Contacts OAuth disconnect when no tokens exist."""
        with patch(
            "app.infrastructure.auth.oauth_service.OAuthService.disconnect_google_contacts"
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
