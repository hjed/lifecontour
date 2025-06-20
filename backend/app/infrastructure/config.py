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
        # Prevent automatic JSON parsing for list fields
        env_parse_none_str="",
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
    allowed_hosts: str | list[str] = Field(
        default=["localhost", "127.0.0.1", "0.0.0.0"],
        description="Allowed hosts for security",
    )

    # CORS settings
    cors_origins: str | list[str] = Field(
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

    # Search settings
    meilisearch_url: str = Field(
        default="http://localhost:7700", description="MeiliSearch server URL"
    )

    # Task queue settings
    redis_url: str = Field(
        default="redis://localhost:6379", description="Redis server URL for task queue"
    )

    # MCP settings
    mcp_enabled: bool = Field(default=True, description="Enable MCP server")
    mcp_mount_path: str = Field(
        default="/mcp-server", description="MCP server mount path"
    )
    meilisearch_api_key: str = Field(default="", description="MeiliSearch API key")
    search_index_prefix: str = Field(
        default="pms_", description="Prefix for search indices"
    )

    # Session settings
    session_secret_key: str = Field(
        default="dev-session-secret-change-in-production",
        description="Secret key for session encryption",
    )

    # OAuth Provider Configuration
    github_client_id: str = Field(default="", description="GitHub OAuth client ID")
    github_client_secret: str = Field(
        default="", description="GitHub OAuth client secret"
    )
    microsoft_client_id: str = Field(
        default="", description="Microsoft OAuth client ID"
    )
    microsoft_client_secret: str = Field(
        default="", description="Microsoft OAuth client secret"
    )
    discord_client_id: str = Field(default="", description="Discord OAuth client ID")
    discord_client_secret: str = Field(
        default="", description="Discord OAuth client secret"
    )

    # Generic OAuth2 Provider (optional)
    oauth_provider_name: str = Field(
        default="", description="Generic OAuth provider name"
    )
    oauth_client_id: str = Field(default="", description="Generic OAuth client ID")
    oauth_client_secret: str = Field(
        default="", description="Generic OAuth client secret"
    )
    oauth_authorization_url: str = Field(
        default="", description="Generic OAuth authorization URL"
    )
    oauth_token_url: str = Field(default="", description="Generic OAuth token URL")
    oauth_userinfo_url: str = Field(
        default="", description="Generic OAuth user info URL"
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
    otel_exporter_otlp_endpoint: str = Field(
        default="", description="OpenTelemetry OTLP exporter endpoint"
    )
    otel_service_name: str = Field(
        default="personal-management-backend", description="OpenTelemetry service name"
    )

    # Development settings
    disable_auth: bool = Field(
        default=False, description="Disable authentication for development/testing"
    )
    otel_resource_attributes: str = Field(
        default="", description="OpenTelemetry resource attributes"
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is supported."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            # Handle comma-separated string
            origins = [origin.strip() for origin in v.split(",") if origin.strip()]
            return origins
        elif isinstance(v, list):
            # Handle list input
            return [str(origin).strip() for origin in v if str(origin).strip()]
        else:
            # Handle other types by converting to string first
            return [str(v).strip()] if str(v).strip() else []

    @field_validator("allowed_hosts")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        """Parse allowed hosts from string or list."""
        if isinstance(v, str):
            # Handle comma-separated string
            hosts = [host.strip() for host in v.split(",") if host.strip()]
            return hosts
        elif isinstance(v, list):
            # Handle list input
            return [str(host).strip() for host in v if str(host).strip()]
        else:
            # Handle other types by converting to string first
            return [str(v).strip()] if str(v).strip() else []


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
