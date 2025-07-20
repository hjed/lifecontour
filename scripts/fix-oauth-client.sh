#!/bin/bash

# Fix OAuth Client Configuration Script
# This script fixes the OAuth client configuration in Hydra to ensure correct redirect URIs

set -e

echo "🔧 Fixing OAuth Client Configuration"
echo "===================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

print_step() {
    echo -e "\n${BLUE}📋 $1${NC}"
}

print_success() {
    print_status $GREEN "✅ $1"
}

print_warning() {
    print_status $YELLOW "⚠️  $1"
}

print_error() {
    print_status $RED "❌ $1"
}

# Check if Hydra is running
print_step "Checking Hydra availability..."
if ! curl -f http://localhost:4445/health/ready >/dev/null 2>&1; then
    print_error "Hydra admin endpoint is not accessible at http://localhost:4445"
    print_error "Make sure Docker Compose is running: docker compose -f docker-compose.dev.yml up -d"
    exit 1
fi

print_success "Hydra is accessible"

# Delete existing client if it exists
print_step "Removing existing OAuth client..."
if curl -s -X DELETE http://localhost:4445/admin/clients/dev-client-id >/dev/null 2>&1; then
    print_success "Existing OAuth client removed"
else
    print_warning "OAuth client may not exist (this is okay)"
fi

# Wait a moment for deletion to complete
sleep 2

# Create new OAuth client with correct configuration
print_step "Creating new OAuth client with correct configuration..."

CLIENT_CONFIG='{
    "client_id": "dev-client-id",
    "client_secret": "dev-client-secret",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["http://localhost:3000/auth/callback"],
    "scope": "openid profile email",
    "skip_consent": true,
    "skip_logout_consent": true,
    "client_name": "Personal Management System (Development)",
    "client_uri": "http://localhost:3000",
    "token_endpoint_auth_method": "client_secret_post"
}'

if curl -X POST http://localhost:4445/admin/clients \
    -H "Content-Type: application/json" \
    -d "$CLIENT_CONFIG" >/dev/null 2>&1; then
    print_success "OAuth client created successfully"
else
    print_error "Failed to create OAuth client"
    exit 1
fi

# Verify client configuration
print_step "Verifying OAuth client configuration..."
CLIENT_INFO=$(curl -s http://localhost:4445/admin/clients/dev-client-id)

if echo "$CLIENT_INFO" | jq -e '.client_id == "dev-client-id"' >/dev/null 2>&1; then
    print_success "Client ID verified"
else
    print_error "Client ID verification failed"
    exit 1
fi

if echo "$CLIENT_INFO" | jq -e '.redirect_uris[] | select(. == "http://localhost:3000/auth/callback")' >/dev/null 2>&1; then
    print_success "Redirect URI verified"
else
    print_error "Redirect URI verification failed"
    echo "Current redirect URIs:"
    echo "$CLIENT_INFO" | jq '.redirect_uris'
    exit 1
fi

if echo "$CLIENT_INFO" | jq -e '.grant_types[] | select(. == "authorization_code")' >/dev/null 2>&1; then
    print_success "Grant types verified"
else
    print_error "Grant types verification failed"
    exit 1
fi

# Display client configuration
print_step "OAuth Client Configuration Summary"
echo "=================================="
echo "Client ID: $(echo "$CLIENT_INFO" | jq -r '.client_id')"
echo "Client Name: $(echo "$CLIENT_INFO" | jq -r '.client_name')"
echo "Redirect URIs:"
echo "$CLIENT_INFO" | jq -r '.redirect_uris[]' | sed 's/^/  - /'
echo "Grant Types:"
echo "$CLIENT_INFO" | jq -r '.grant_types[]' | sed 's/^/  - /'
echo "Response Types:"
echo "$CLIENT_INFO" | jq -r '.response_types[]' | sed 's/^/  - /'
echo "Scope: $(echo "$CLIENT_INFO" | jq -r '.scope')"
echo "Skip Consent: $(echo "$CLIENT_INFO" | jq -r '.skip_consent')"

# Test OAuth endpoints
print_step "Testing OAuth endpoints..."

# Test authorization endpoint
AUTH_URL="http://localhost:4444/oauth2/auth?client_id=dev-client-id&response_type=code&scope=openid%20profile%20email&redirect_uri=http://localhost:3000/auth/callback&state=test-state"

if curl -s -o /dev/null -w "%{http_code}" "$AUTH_URL" | grep -q "302\|200"; then
    print_success "Authorization endpoint is working"
else
    print_warning "Authorization endpoint may have issues"
fi

# Test token endpoint (should return 400 without proper request)
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:4444/oauth2/token" | grep -q "400\|405"; then
    print_success "Token endpoint is accessible"
else
    print_warning "Token endpoint may have issues"
fi

# Test userinfo endpoint (should return 401 without token)
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:4444/userinfo" | grep -q "401"; then
    print_success "Userinfo endpoint is accessible"
else
    print_warning "Userinfo endpoint may have issues"
fi

print_step "OAuth Client Fix Complete!"
echo "=========================="
print_success "OAuth client has been successfully configured"
echo ""
echo "🔗 You can now test the OAuth flow:"
echo "   1. Open http://localhost:3000/auth/login"
echo "   2. Click the OAuth login button"
echo "   3. Complete the authorization flow"
echo ""
echo "🧪 Run tests to verify:"
echo "   cd frontend && npm run test:e2e -- oauth-flow.spec.ts"
echo ""
echo "🔍 Debug information:"
echo "   Authorization URL: $AUTH_URL"
echo "   Token URL: http://localhost:4444/oauth2/token"
echo "   Userinfo URL: http://localhost:4444/userinfo"
echo ""

print_success "OAuth client configuration fix completed successfully!"
