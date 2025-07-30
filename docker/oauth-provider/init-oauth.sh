#!/bin/sh

# OAuth Provider Initialization Script
# This script creates the OAuth client automatically for development and testing environments

set -e

# Environment-specific configuration with defaults
OAUTH_PROVIDER_HOST=${OAUTH_PROVIDER_HOST:-oauth-provider-dev}
OAUTH_ADMIN_PORT=${OAUTH_ADMIN_PORT:-4445}
CLIENT_ID=${CLIENT_ID:-dev-client-id}
CLIENT_SECRET=${CLIENT_SECRET:-dev-client-secret}
ENVIRONMENT=${ENVIRONMENT:-development}
FRONTEND_URL=${FRONTEND_URL:-http://localhost:3000}
PUBLIC_PORT=${PUBLIC_PORT:-4444}
ADMIN_PORT_EXTERNAL=${ADMIN_PORT_EXTERNAL:-4445}

echo "🔧 Starting OAuth provider initialization for ${ENVIRONMENT}..."

# Colors for output (if supported)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

print_status() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

print_step() {
    print_status "$BLUE" "📋 $1"
}

print_success() {
    print_status "$GREEN" "✅ $1"
}

print_warning() {
    print_status "$YELLOW" "⚠️  $1"
}

print_error() {
    print_status "$RED" "❌ $1"
}

# Wait for Hydra to be ready with better error handling
print_step "Waiting for Hydra to be ready..."
max_attempts=60  # Increased timeout for environments
attempt=0

HEALTH_URL="http://${OAUTH_PROVIDER_HOST}:${OAUTH_ADMIN_PORT}/health/ready"
print_step "Checking health at: ${HEALTH_URL}"

while [ $attempt -lt $max_attempts ]; do
    if curl -f -s "${HEALTH_URL}" >/dev/null 2>&1; then
        print_success "Hydra is ready!"
        break
    fi

    # Show progress every 10 attempts
    if [ $((attempt % 10)) -eq 0 ] && [ $attempt -gt 0 ]; then
        print_step "Still waiting for Hydra... (attempt $((attempt + 1))/$max_attempts)"
        # Show more detailed error info every 10 attempts
        echo "Attempting to connect to: ${HEALTH_URL}"
        curl_output=$(curl -f -s "${HEALTH_URL}" 2>&1 || true)
        echo "Curl response: $curl_output"
    fi

    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    print_error "Hydra failed to start within expected time"
    print_error "Final connection attempt to: ${HEALTH_URL}"
    curl -f -s "${HEALTH_URL}" 2>&1 || true
    print_error "Check Hydra logs for more details"
    exit 1
fi

# Additional wait to ensure Hydra is fully initialized
sleep 3

# Check if client already exists
print_step "Checking if OAuth client already exists..."
CLIENT_CHECK_URL="http://${OAUTH_PROVIDER_HOST}:${OAUTH_ADMIN_PORT}/admin/clients/${CLIENT_ID}"
echo "Checking client at: ${CLIENT_CHECK_URL}"

# Use curl without -f to avoid exit code 7, check HTTP status instead
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${CLIENT_CHECK_URL}" 2>/dev/null || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
    print_warning "OAuth client already exists, removing it first..."
    if curl -X DELETE -s "${CLIENT_CHECK_URL}" >/dev/null 2>&1; then
        print_success "Existing client removed"
        sleep 2  # Wait for deletion to complete
    else
        print_warning "Failed to remove existing client, continuing anyway..."
    fi
elif [ "$HTTP_STATUS" = "404" ]; then
    print_step "Client does not exist yet (HTTP 404) - this is expected"
else
    print_warning "Unexpected response when checking client (HTTP $HTTP_STATUS) - continuing anyway..."
fi
fi

# Create OAuth client with comprehensive configuration
print_step "Creating OAuth client for ${ENVIRONMENT}..."

CLIENT_CONFIG=$(cat <<EOF
{
    "client_id": "${CLIENT_ID}",
    "client_secret": "${CLIENT_SECRET}",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["${FRONTEND_URL}/auth/callback"],
    "post_logout_redirect_uris": ["${FRONTEND_URL}/"],
    "scope": "openid profile email",
    "audience": [],
    "skip_consent": true,
    "skip_logout_consent": true,
    "client_name": "Personal Management System (${ENVIRONMENT})",
    "client_uri": "${FRONTEND_URL}",
    "logo_uri": "",
    "policy_uri": "",
    "tos_uri": "",
    "token_endpoint_auth_method": "client_secret_post",
    "userinfo_signed_response_alg": "none",
    "subject_type": "public"
}
EOF
)

CREATE_CLIENT_URL="http://${OAUTH_PROVIDER_HOST}:${OAUTH_ADMIN_PORT}/admin/clients"
if curl -X POST "${CREATE_CLIENT_URL}" \
    -H "Content-Type: application/json" \
    -d "$CLIENT_CONFIG" \
    -f -s >/dev/null 2>&1; then
    print_success "OAuth client created successfully!"
else
    print_error "Failed to create OAuth client"
    print_error "Response from Hydra:"
    curl -X POST "${CREATE_CLIENT_URL}" \
        -H "Content-Type: application/json" \
        -d "$CLIENT_CONFIG" 2>&1 || true
    exit 1
fi

# Verify client configuration
print_step "Verifying OAuth client configuration..."
CLIENT_INFO=$(curl -s "${CLIENT_CHECK_URL}" 2>/dev/null)

if [ $? -eq 0 ] && echo "$CLIENT_INFO" | grep -q "\"client_id\":\"${CLIENT_ID}\""; then
    print_success "Client verification successful"

    # Extract and display key configuration
    echo ""
    print_step "OAuth Client Configuration (${ENVIRONMENT}):"
    echo "  Client ID: ${CLIENT_ID}"
    echo "  Client Name: Personal Management System (${ENVIRONMENT})"
    echo "  Redirect URI: ${FRONTEND_URL}/auth/callback"
    echo "  Grant Types: authorization_code, refresh_token"
    echo "  Scope: openid profile email"
    echo "  Skip Consent: true"
else
    print_warning "Client verification failed, but client may still work"
fi

# Test basic endpoints
print_step "Testing OAuth endpoints..."

# Test authorization endpoint
# Use the OAuth provider host for internal container communication
if [ -n "$OAUTH_PROVIDER_HOST" ]; then
    # Running in Docker - use service name
    PUBLIC_URL="http://${OAUTH_PROVIDER_HOST}:${PUBLIC_PORT}"
    echo "Using Docker service URL: $PUBLIC_URL"
else
    # Running locally - use localhost
    PUBLIC_URL="http://localhost:${PUBLIC_PORT}"
    echo "Using localhost URL: $PUBLIC_URL"
fi

AUTH_URL="${PUBLIC_URL}/oauth2/auth?client_id=${CLIENT_ID}&response_type=code&scope=openid%20profile%20email&redirect_uri=${FRONTEND_URL}/auth/callback&state=test"

echo "Testing authorization endpoint: $AUTH_URL"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$AUTH_URL")
echo "Received HTTP code: $HTTP_CODE"

if echo "$HTTP_CODE" | grep -E "^(200|302)$" >/dev/null; then
    print_success "Authorization endpoint is working (HTTP $HTTP_CODE)"
else
    print_warning "Authorization endpoint test inconclusive (HTTP $HTTP_CODE)"
    # Don't fail the initialization for this - it might be a network timing issue
    echo "Note: This doesn't prevent OAuth from working, just means the test couldn't verify it"
fi

print_success "OAuth provider initialization complete for ${ENVIRONMENT}!"
echo ""
print_step "🔗 OAuth Configuration Summary (${ENVIRONMENT}):"
# For display purposes, show localhost URLs (what users would access)
DISPLAY_URL="http://localhost:${PUBLIC_PORT}"
echo "  Authorization URL: ${DISPLAY_URL}/oauth2/auth"
echo "  Token URL: ${DISPLAY_URL}/oauth2/token"
echo "  Userinfo URL: ${DISPLAY_URL}/userinfo"
echo "  Admin URL: http://localhost:${ADMIN_PORT_EXTERNAL}"
echo ""
print_step "🧪 Test the OAuth flow:"
echo "  1. Run tests: npm run test:e2e -- oauth-flow.spec.ts"
echo "  2. Or manually test at ${FRONTEND_URL}/auth/login"
echo ""
