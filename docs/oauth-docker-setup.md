# OAuth Docker Integration Guide

This guide explains how to set up and verify the OAuth authentication flow with the Docker Compose development environment.

## Overview

The OAuth integration uses Hydra as the OAuth2/OpenID Connect provider in development, providing a complete OAuth flow without requiring external providers like GitHub or Google.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │    Backend      │    │  Hydra OAuth    │
│  (Port 3000)    │    │  (Port 8000)    │    │  (Port 4444)    │
│                 │    │                 │    │                 │
│ Login Page      │───▶│ OAuth Endpoints │───▶│ Authorization   │
│ Callback Page   │◀───│ Session Mgmt    │◀───│ Token Exchange  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
                                               ┌─────────────────┐
                                               │   OAuth UI      │
                                               │  (Port 3001)    │
                                               │                 │
                                               │ Client Mgmt     │
                                               │ User Interface  │
                                               └─────────────────┘
```

## Services Configuration

### 1. Hydra OAuth Provider (`oauth-provider-dev`)
- **Public Port**: 4444 (OAuth endpoints)
- **Admin Port**: 4445 (Management API)
- **Database**: SQLite in-memory (development only)
- **Configuration**: Auto-creates OAuth client on startup

### 2. OAuth UI (`oauth-ui-dev`)
- **Port**: 3001
- **Purpose**: Web interface for managing OAuth clients and users
- **Dependencies**: Hydra OAuth Provider

### 3. Backend (`backend-dev`)
- **Port**: 8000
- **OAuth Configuration**:
  - Provider: `generic`
  - Client ID: `dev-client-id`
  - Client Secret: `dev-client-secret`
  - Authorization URL: `http://localhost:4444/oauth2/auth`
  - Token URL: `http://oauth-provider-dev:4444/oauth2/token`

### 4. Frontend (`frontend-dev`)
- **Port**: 3000
- **OAuth Integration**: Login page with OAuth buttons
- **Callback Handling**: `/auth/callback` route

## Quick Start

### 1. Start Development Environment

```bash
# Start all services including OAuth
docker-compose -f docker-compose.dev.yml up -d

# Check service status
docker-compose -f docker-compose.dev.yml ps
```

### 2. Verify OAuth Setup

```bash
# Run the verification script (Linux/Mac)
./scripts/verify-oauth-docker.sh

# Or manually verify endpoints:
curl http://localhost:4444/.well-known/openid_configuration
curl http://localhost:4445/admin/clients/dev-client-id
curl http://localhost:8000/api/health
```

### 3. Test OAuth Flow

1. **Open Frontend**: http://localhost:3000
2. **Navigate to Login**: http://localhost:3000/auth/login
3. **Click OAuth Button**: Should redirect to Hydra
4. **Complete Authorization**: Follow Hydra's consent flow
5. **Return to App**: Should be authenticated

## Manual Verification Steps

### 1. Check Hydra Health

```bash
# Public endpoint health
curl http://localhost:4444/health/ready

# Admin endpoint health
curl http://localhost:4445/health/ready

# OpenID configuration
curl http://localhost:4444/.well-known/openid_configuration | jq
```

### 2. Verify OAuth Client

```bash
# Get client configuration
curl http://localhost:4445/admin/clients/dev-client-id | jq

# Expected response should include:
# - client_id: "dev-client-id"
# - redirect_uris: ["http://localhost:3000/auth/callback",
#                   "http://localhost:8000/mcp-server/auth/callback"]
# - grant_types: ["authorization_code", "refresh_token"]
```

### 3. Test Backend OAuth Endpoints

```bash
# Session endpoint (should return 401 when not authenticated)
curl -i http://localhost:8000/api/auth/session

# Login endpoint (should return 405 for GET, needs POST)
curl -i http://localhost:8000/api/auth/login
```

### 4. Test Frontend Integration

```bash
# Login page should contain OAuth elements
curl http://localhost:3000/auth/login | grep -i "continue with\|oauth"

# Callback page should handle OAuth parameters
curl "http://localhost:3000/auth/callback?code=test&state=test"
```

## Running Playwright Tests

### 1. OAuth Flow Tests

```bash
cd frontend

# Run comprehensive OAuth flow tests
npm run test:e2e -- oauth-flow.spec.ts

# Run OAuth error handling tests
npm run test:e2e -- oauth-error-handling.spec.ts

# Run Docker integration tests
npm run test:e2e -- oauth-docker-integration.spec.ts
```

### 2. Test Configuration

The Playwright tests are configured to:
- Test against real backend (localhost:8000)
- Use real Hydra OAuth provider (localhost:4444)
- Not mock critical OAuth parts
- Verify complete flow including session management

## Troubleshooting

### Common Issues

#### 1. Hydra Not Starting
```bash
# Check Hydra logs
docker-compose -f docker-compose.dev.yml logs oauth-provider-dev

# Common causes:
# - Port 4444/4445 already in use
# - Insufficient memory
# - Network connectivity issues
```

#### 2. OAuth Client Not Created
```bash
# Check initialization logs
docker-compose -f docker-compose.dev.yml logs oauth-provider-dev | grep "OAuth client"

# Manually create client if needed:
curl -X POST http://localhost:4445/admin/clients \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "dev-client-id",
    "client_secret": "dev-client-secret",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["http://localhost:3000/auth/callback", "http://localhost:8000/mcp-server/auth/callback"],
    "scope": "openid profile email"
  }'
```

#### 3. Backend OAuth Configuration Issues
```bash
# Check backend environment variables
docker-compose -f docker-compose.dev.yml exec backend-dev env | grep OAUTH

# Expected variables:
# OAUTH_PROVIDER_NAME=generic
# OAUTH_CLIENT_ID=dev-client-id
# OAUTH_CLIENT_SECRET=dev-client-secret
# OAUTH_AUTHORIZATION_URL=http://localhost:4444/oauth2/auth
# OAUTH_TOKEN_URL=http://oauth-provider-dev:4444/oauth2/token
```

#### 4. Frontend OAuth Buttons Not Showing
```bash
# Check if backend OAuth is configured
curl http://localhost:8000/api/auth/session

# Check frontend logs
docker-compose -f docker-compose.dev.yml logs frontend-dev
```

### Network Issues

If services can't communicate:

```bash
# Check Docker network
docker network ls | grep personal-management-dev

# Inspect network configuration
docker network inspect personal-management-dev

# Restart services if needed
docker-compose -f docker-compose.dev.yml restart
```

## Development Workflow

### 1. Making OAuth Changes

1. **Update Configuration**: Modify `docker-compose.dev.yml`
2. **Restart Services**: `docker-compose -f docker-compose.dev.yml restart`
3. **Verify Changes**: Run verification script or manual tests
4. **Test with Playwright**: Run OAuth test suites

### 2. Testing OAuth Flows

1. **Start Clean Environment**: `docker-compose -f docker-compose.dev.yml down && docker-compose -f docker-compose.dev.yml up -d`
2. **Wait for Initialization**: Services need 30-60 seconds to fully start
3. **Run Tests**: Execute Playwright tests or manual verification
4. **Check Logs**: Review service logs for any issues

### 3. Debugging OAuth Issues

1. **Enable Debug Logging**: Set `LOG_LEVEL=DEBUG` in backend environment
2. **Monitor Network Traffic**: Use browser dev tools or curl with `-v`
3. **Check Session State**: Verify session storage and cookies
4. **Validate OAuth Flow**: Follow OAuth2 specification compliance

## Security Considerations

### Development Environment

- Uses SQLite in-memory database (data lost on restart)
- Simplified consent flow (`skip_consent: true`)
- Debug logging enabled
- Not suitable for production use

### Production Deployment

For production, replace Hydra with:
- External OAuth providers (GitHub, Google, etc.)
- Persistent database for Hydra
- Proper SSL/TLS configuration
- Secure session management
- Rate limiting and security headers

## Additional Resources

- [Hydra Documentation](https://www.ory.sh/hydra/docs/)
- [OAuth 2.0 Specification](https://tools.ietf.org/html/rfc6749)
- [OpenID Connect Specification](https://openid.net/connect/)
- [Playwright Testing Guide](https://playwright.dev/docs/intro)
