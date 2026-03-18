# MCP Server Setup and Configuration

This document describes how to set up and configure the MCP (Model Context Protocol) server for the Personal Management System.

## Overview

The MCP server provides AI access to personal management data through the Model Context Protocol. It's built using FastMCP v3 and integrates seamlessly with the existing FastAPI application.

## Architecture

### Domain-Based Organization

The MCP implementation follows the same domain-based architecture as the rest of the system:

```
backend/app/mcp/
├── __init__.py
├── server.py              # Main FastMCP server composition + OAuth auth factory
├── domains/               # Domain-specific MCP tools
│   ├── __init__.py
│   ├── contacts/          # Contact domain MCP tools
│   │   ├── __init__.py
│   │   ├── tools.py       # Contact MCP tools
│   │   └── schemas.py     # Contact MCP schemas
│   ├── journals/          # Journal domain MCP tools
│   ├── calendar/          # Future: Calendar domain MCP tools
│   └── photos/            # Future: Photos domain MCP tools
├── auth/                  # MCP authentication
│   └── __init__.py
└── shared/                # Shared MCP utilities
    ├── __init__.py
    └── dependencies.py    # MCP dependency injection helpers
```

### Integration with FastAPI

The MCP server is mounted as a sub-application in the main FastAPI app:

- **Mount Path**: `/mcp-server` (configurable via `MCP_MOUNT_PATH`)
- **MCP Endpoint**: `/mcp-server`
- **Authentication**: OAuth via FastMCP's built-in providers (GitHub, Google, Discord, or generic OAuth)
- **Transport**: Streamable HTTP for web compatibility

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# MCP Configuration
MCP_ENABLED=true
MCP_MOUNT_PATH=/mcp-server
MCP_BASE_URL=http://localhost:8000    # External base URL for OAuth callbacks
```

### Settings

The MCP server is configured through the main application settings:

```python
class Settings(BaseSettings):
    # MCP settings
    mcp_enabled: bool = Field(default=True, description="Enable MCP server")
    mcp_mount_path: str = Field(default="/mcp-server", description="MCP server mount path")
    mcp_base_url: str = Field(default="http://localhost:8000", description="External base URL for MCP OAuth")
```

## Available Tools

### Contact Domain Tools

#### `get_contact`

Retrieves comprehensive contact information by ID.

**Parameters:**
- `contact_id` (int): The unique identifier of the contact

**Returns:**
AI-friendly JSON containing:
- Basic contact details (name, email, phone)
- Associated tags for categorization
- Contextual summary for AI understanding

**Example Response:**
```json
{
  "id": "123",
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "tags": ["friend", "work"],
  "summary": "John Doe is a contact tagged as: friend, work. Primary email: john@example.com. Primary phone: +1234567890."
}
```

## Authentication

The MCP server uses OAuth authentication via FastMCP's built-in providers:

1. **OAuth Proxy**: FastMCP acts as an OAuth proxy, bridging MCP clients with your configured OAuth provider
2. **Provider Auto-Selection**: The first configured provider is used (priority: generic OAuth → GitHub → Google → Discord)
3. **User Context**: Authenticated user information is available to MCP tools via OAuth tokens

### OAuth Provider Setup

The MCP auth factory auto-selects based on configured OAuth credentials in your `.env`:

| Provider | Required Settings |
|---|---|
| Generic OAuth | `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_AUTHORIZATION_URL`, `OAUTH_TOKEN_URL`, `OAUTH_INTROSPECTION_URL` |
| GitHub | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` |
| Google | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Discord | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` |

### OAuth Callback URL

> **Important**: You must register the MCP callback URL as an authorized redirect URI in your OAuth provider's app settings:
>
> ```
> {MCP_BASE_URL}{MCP_MOUNT_PATH}/auth/callback
> ```
>
> For example: `https://your-domain.com/mcp-server/auth/callback`
>
> This is separate from the frontend OAuth callback URL.

## Development

### Adding New Tools

1. **Create Tool Function**: Add to appropriate domain tools file
2. **Register Tool**: Use `@mcp.tool` decorator
3. **Add Tests**: Unit tests for tool logic
4. **Update Documentation**: Document tool parameters and responses

Example:
```python
@mcp.tool
async def get_contact(
    contact_id: Annotated[int, Field(description="The unique identifier of the contact")]
) -> str:
    """Get contact details by ID for AI analysis."""
    # Implementation...
```

### Adding New Domains

1. **Create Domain Directory**: `backend/app/mcp/domains/new_domain/`
2. **Add Tools Module**: `tools.py` with domain-specific tools
3. **Add Schemas Module**: `schemas.py` with AI-friendly response formats
4. **Register in Server**: Add to `create_mcp_server()` function
5. **Add Tests**: Unit and integration tests

### Testing

Run MCP-specific tests:

```bash
# Unit tests
cd backend
uv run pytest tests/unit/mcp/ -v

# Integration tests (when available)
uv run pytest tests/integration/mcp/ -v
```

## Health Monitoring

The MCP server status is included in the application health checks:

- **Endpoint**: `/api/health/detailed`
- **Status**: Shows MCP server enabled/disabled state
- **Configuration**: Displays mount path and settings

## Troubleshooting

### Common Issues

1. **401 Unauthorized**: Check session authentication
2. **404 Not Found**: Verify MCP mount path configuration
3. **Tool Not Found**: Ensure tools are properly registered

### Debugging

Enable debug logging to see MCP operations:

```bash
LOG_LEVEL=DEBUG
```

Check logs for MCP-specific messages:
- `MCP: Creating FastMCP server`
- `MCP: Registering contact domain tools`
- `MCP: Server mounted successfully`

## Future Enhancements

### Planned Domains

- **Journal**: Personal journaling and note-taking tools
- **Calendar**: Event and scheduling management tools
- **Photos**: Image and media management tools

### Planned Features

- **Resource Access**: File and document retrieval
- **Progress Reporting**: Long-running operation progress
- **Sampling**: AI-to-AI communication capabilities
- **Advanced Search**: Cross-domain search tools

## References

- [FastMCP v3 Documentation](https://gofastmcp.com)
- [FastMCP Auth Providers](https://gofastmcp.com/servers/auth)
- [FastMCP FastAPI Integration](https://gofastmcp.com/integrations/fastapi)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
