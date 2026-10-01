# MCP Server Setup and Configuration

This document describes how to set up and configure the MCP (Model Context Protocol) server for the Personal Management System.

## Overview

The MCP server provides AI access to personal management data through the Model Context Protocol. It's built using FastMCP 4 (on the MCP Python SDK v2) and integrates seamlessly with the existing FastAPI application.

## Architecture

### Domain-Based Organization

The MCP implementation follows the same domain-based architecture as the rest of the system:

```
backend/app/mcp/
├── __init__.py
├── server.py              # Main FastMCP server composition
├── domains/               # Domain-specific MCP tools
│   ├── __init__.py
│   ├── contacts/          # Contact domain MCP tools
│   │   ├── __init__.py
│   │   ├── tools.py       # Contact MCP tools
│   │   └── schemas.py     # Contact MCP schemas
│   ├── journal/           # Future: Journal domain MCP tools
│   ├── calendar/          # Future: Calendar domain MCP tools
│   └── photos/            # Future: Photos domain MCP tools
├── auth/                  # MCP authentication
│   ├── __init__.py
│   └── providers.py       # OAuth provider factory
└── shared/                # Shared MCP utilities
    ├── __init__.py
    └── dependencies.py    # MCP dependency injection helpers
```

### Integration with FastAPI

The MCP server is mounted as a sub-application in the main FastAPI app:

- **Mount Path**: `/mcp-server` (configurable via `MCP_MOUNT_PATH`)
- **MCP Endpoint**: `/mcp-server/mcp`
- **Authentication**: Shared OAuth session with REST API
- **Transport**: Streamable HTTP for web compatibility

### Protocol Versions

One endpoint serves both MCP protocol eras, chosen per request by the
`MCP-Protocol-Version` header — there is no server setting, and neither can be
switched off:

- **Sessionless (`2026-07-28`)**: no `initialize` handshake and no
  `mcp-session-id`. Each request carries its protocol version and client
  capabilities in `params._meta`, and repeats the method (and tool name) in the
  `Mcp-Method` / `Mcp-Name` headers, which must match the body. Any replica can
  answer any request. Current clients, including `fastmcp.Client`, negotiate
  this by default.
- **Handshake (≤ `2025-11-25`)**: `initialize` returns an `mcp-session-id` that
  later requests send back. Older clients keep working unchanged.

Authentication and the Dishka request container apply identically to both.
Because the sessionless era has no back-channel to the client, tools must not
rely on server-initiated requests (sampling, elicitation, roots) or on state
kept between calls. `tests/integration/mcp/test_mcp_protocol_eras.py` pins
both eras against the mounted app.

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# MCP Configuration
MCP_ENABLED=true
MCP_MOUNT_PATH=/mcp-server
```

### Settings

The MCP server is configured through the main application settings:

```python
class Settings(BaseSettings):
    # MCP settings
    mcp_enabled: bool = Field(default=True, description="Enable MCP server")
    mcp_mount_path: str = Field(default="/mcp-server", description="MCP server mount path")
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

The MCP server uses FastMCP's built-in OAuth proxy authentication, providing full OAuth 2.1 compliance with `.well-known` discovery endpoints. This enables MCP clients (Claude Desktop, etc.) to authenticate using the same OAuth providers configured for the web UI.

### How It Works

1. **Provider Selection**: The first configured OAuth provider is used (priority: Generic > GitHub > Microsoft > Discord)
2. **OAuth Proxy**: FastMCP acts as an OAuth proxy, forwarding authorization to the upstream provider
3. **`.well-known` Discovery**: Standard OAuth discovery endpoints are exposed at root level
4. **Token Validation**: FastMCP issues its own JWT tokens after validating the upstream token against the IdP's JWKS

### Who an MCP request acts as

Everything an MCP tool writes is stamped with a `user_id`, and owner-scoped REST
endpoints filter on it — so getting this wrong makes MCP-created data invisible
in the web UI rather than merely mislabelled.

The identity comes from the **upstream `id_token`**, not from the FastMCP token.
Under the generic provider, `McpOidcProxy` (`app/mcp/auth/providers.py`) verifies
that `id_token` against the IdP's JWKS on every request, and its verified
`sub`/`email`/`name` claims name the acting user. The `id_token` is verified in
preference to the access token because OIDC guarantees it is a JWT, whereas
access tokens may be opaque (Hydra's are, in development).

### What the JWKS check does and does not cover

Verification is a local, offline check against the IdP's published keys: it enforces
the token's signature, issuer, audience and expiry. An expired upstream session
therefore stops working — the request either refreshes transparently (when the IdP
issued a refresh token) or returns 401 and the client re-authenticates.

It is **not** a liveness check. Revoking a session at the IdP does not retire the
signing key, so an already-issued `id_token` keeps verifying until its own `exp`.
Revocation surfaces indirectly at the next refresh, which the IdP refuses, so the
exposure window after a revocation is roughly the upstream access-token lifetime.
Shortening that lifetime shortens the window; detecting revocation sooner needs
introspection or a userinfo probe per request, tracked in
[#1322](https://github.com/hjed/lifecontour/issues/1322).

This requires the `openid` scope, which `OAUTH_SCOPES` includes by default. A
token that reaches the server with no `sub` claim is **refused** — it does not
fall back to the OAuth client id, because a client identifies the application
rather than the person using it, and treating it as a user makes every caller
sharing that client look like one account.

### Configuration

The MCP OAuth auth reuses the existing OAuth provider credentials and the `WEBHOOK_BASE_URL` setting:

```bash
# Required for MCP OAuth (public URL of your server)
WEBHOOK_BASE_URL=https://your-server.example.com

# One of these OAuth providers must be configured:

# Generic OAuth (highest priority)
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
OAUTH_AUTHORIZATION_URL=https://auth.example.com/authorize
OAUTH_TOKEN_URL=https://auth.example.com/token
# REQUIRED for the generic provider. MCP discovers the IdP's configuration from
# {OAUTH_ISSUER}/.well-known/openid-configuration at startup and verifies
# upstream id_tokens against the JWKS it advertises. The server refuses to start
# without it rather than accepting tokens it cannot check.
OAUTH_ISSUER=https://auth.example.com

# GitHub
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret

# Microsoft / Azure AD
MICROSOFT_CLIENT_ID=your-ms-client-id
MICROSOFT_CLIENT_SECRET=your-ms-client-secret
MICROSOFT_TENANT_ID=common  # optional, defaults to "common"

# Discord
DISCORD_CLIENT_ID=your-discord-client-id
DISCORD_CLIENT_SECRET=your-discord-client-secret
```

#### Provider notes

**Kanidm.** The issuer is scoped to the OAuth client, so `OAUTH_ISSUER` is not the
bare Kanidm URL:

```bash
OAUTH_ISSUER=https://idm.example.com/oauth2/openid/<client-id>
```

Kanidm signs `id_token`s with **ES256** unless legacy crypto is enabled. The
signing algorithm is read from the discovery document, so nothing needs
configuring — but note that an IdP advertising only algorithms we do not accept
(or only symmetric `HS*`, which JWKS verification cannot use) fails at startup
instead of rejecting every token later.

**Hydra (development).** FastMCP's OAuth proxy serves its own callback at
`{WEBHOOK_BASE_URL}{MCP_MOUNT_PATH}/auth/callback` — `http://localhost:8000/mcp-server/auth/callback`
on the default dev stack — and Hydra refuses an authorization request whose
`redirect_uri` is not registered on the client. `docker/oauth-provider/init-oauth.sh`
therefore registers that URI alongside the web app's, building it from the same
`WEBHOOK_BASE_URL` and `MCP_MOUNT_PATH` that `docker-compose.yml` passes to the
backend, so the registered address cannot drift from the one the MCP server
listens on. Override either variable and both sides follow.

Hydra derives every advertised endpoint from its issuer,
which has to stay browser-facing. The backend reaches it over the Docker network
instead, so `docker-compose.yml` sets `WEBFINGER_OIDC_DISCOVERY_TOKEN_URL` and
`WEBFINGER_OIDC_DISCOVERY_JWKS_URL` to the container-internal address and points
the backend at `OAUTH_DISCOVERY_URL` there. `OAUTH_DISCOVERY_URL` exists for
exactly this split: it is where the metadata is *fetched from*, while
`OAUTH_ISSUER` remains the issuer tokens are minted under, and the two are
cross-checked before the document's keys are trusted.

### Discovery Endpoints

When auth is enabled, the following `.well-known` endpoints are available:

- `/.well-known/oauth-authorization-server/mcp-server` — OAuth authorization server metadata
- `/.well-known/oauth-protected-resource/mcp-server/mcp` — Protected resource metadata

### Development Mode

Set `DISABLE_AUTH=true` to disable OAuth for local development. MCP endpoints will be accessible without authentication.

## Development

### Adding New Tools

1. **Create Tool Function**: Add to appropriate domain tools file
2. **Register Tool**: Use `@mcp.tool` decorator
3. **Add Tests**: Unit tests for tool logic
4. **Document in Code**: Tools are documented by their docstrings and
   parameter/response schema descriptions — do not duplicate tool docs here,
   as they go stale

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
- **Advanced Search**: Cross-domain search tools

## References

- [FastMCP Documentation](https://gofastmcp.com/llms.txt)
- [Upgrading from FastMCP 3](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)
- [FastAPI Integration Guide](https://gofastmcp.com/deployment/asgi.md)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
