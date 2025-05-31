"""
Application configuration using Pydantic Settings.

Handles environment variables, defaults, and validation for all
application settings including database, security, and external services.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        description="Secret key for JWT tokens",
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    allowed_hosts: list[str] = Field(
        default=["localhost", "127.0.0.1", "0.0.0.0"],
        description="Allowed hosts for security",
    )

    # CORS settings
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins",
    )

    # Database settings
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/personal_management",
        description="PostgreSQL database URL",
    )
    database_echo: bool = Field(
        default=False, description="Enable SQLAlchemy query logging"
    )

    # Security settings
    access_token_expire_minutes: int = Field(
        default=30, description="JWT access token expiration in minutes"
    )
    refresh_token_expire_days: int = Field(
        default=7, description="JWT refresh token expiration in days"
    )

    # External services
    google_client_id: str = Field(default="", description="Google OAuth client ID")
    google_client_secret: str = Field(
        default="", description="Google OAuth client secret"
    )
    immich_base_url: str = Field(default="", description="Immich instance base URL")
    immich_api_key: str = Field(default="", description="Immich API key")

    # Observability
    enable_telemetry: bool = Field(
        default=False, description="Enable OpenTelemetry instrumentation"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is supported."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        """Parse allowed hosts from string or list."""
        if isinstance(v, str):
            return [host.strip() for host in v.split(",")]
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
