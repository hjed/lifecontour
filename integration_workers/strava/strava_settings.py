"""
Strava worker configuration settings.

Loads configuration from environment variables with Pydantic BaseSettings.
Secrets are isolated to the worker's own .env file.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class StravaSettings(BaseSettings):
    """Configuration for Strava integration worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database connection
    database_url: SecretStr

    # Redis connection
    redis_url: str = "redis://redis:6379"

    # Strava API credentials
    strava_client_id: str
    strava_client_secret: SecretStr

    # Encryption key for tokens
    encryption_key: SecretStr

    # Worker configuration
    worker_id: str = "strava-worker"
    log_level: str = "INFO"

    # Observability
    enable_telemetry: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "strava-worker"
    otel_resource_attributes: str = ""
