#!/bin/sh

# OAuth Provider Initialization Script
# This script creates the OAuth client automatically when the container starts
# It runs in the background after Hydra has started

set -e

echo "🔧 Starting OAuth provider initialization..."

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
max_attempts=60  # Increased timeout
attempt=0

# Use the Docker service name for internal network communication
HYDRA_ADMIN_URL="http://oauth-provider-dev:4445"

while [ $attempt -lt $max_attempts ]; do
    if curl -f -s ${HYDRA_ADMIN_URL}/health/ready >/dev/null 2>&1; then
        print_success "Hydra is ready!"
        break
    fi

    # Show progress every 10 attempts
    if [ $((attempt % 10)) -eq 0 ] && [ $attempt -gt 0 ]; then
        print_step "Still waiting for Hydra... (attempt $((attempt + 1))/$max_attempts)"
    fi

    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -eq $max_attempts ]; then
    print_error "Hydra failed to start within expected time"
    print_error "Check Hydra logs: docker logs pms-oauth-dev"
    exit 1
fi

# Additional wait to ensure Hydra is fully initialized
sleep 3

# Check if client already exists
print_step "Checking if OAuth client already exists..."
if curl -f -s ${HYDRA_ADMIN_URL}/admin/clients/dev-client-id >/dev/null 2>&1; then
    print_warning "OAuth client already exists, removing it first..."
    if curl -X DELETE -s ${HYDRA_ADMIN_URL}/admin/clients/dev-client-id >/dev/null 2>&1; then
        print_success "Existing client removed"
        sleep 2  # Wait for deletion to complete
    else
        print_warning "Failed to remove existing client, continuing anyway..."
    fi
fi

# Create OAuth client with comprehensive configuration
print_step "Creating OAuth client..."

CLIENT_CONFIG='{
    "client_id": "dev-client-id",
    "client_secret": "dev-client-secret",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["http://localhost:3000/auth/callback"],
    "post_logout_redirect_uris": ["http://localhost:3000/"],
    "scope": "openid profile email",
    "audience": [],
    "skip_consent": true,
    "skip_logout_consent": true,
    "client_name": "Personal Management System (Development)",
    "client_uri": "http://localhost:3000",
    "logo_uri": "",
    "policy_uri": "",
    "tos_uri": "",
    "token_endpoint_auth_method": "client_secret_post",
    "userinfo_signed_response_alg": "none",
    "subject_type": "public"
}'

if curl -X POST ${HYDRA_ADMIN_URL}/admin/clients \
    -H "Content-Type: application/json" \
    -d "$CLIENT_CONFIG" \
    -f -s >/dev/null 2>&1; then
    print_success "OAuth client created successfully!"
else
    print_error "Failed to create OAuth client"
    print_error "Response from Hydra:"
    curl -X POST ${HYDRA_ADMIN_URL}/admin/clients \
        -H "Content-Type: application/json" \
        -d "$CLIENT_CONFIG" 2>&1 || true
    exit 1
fi

# Verify client configuration
print_step "Verifying OAuth client configuration..."
CLIENT_INFO=$(curl -s ${HYDRA_ADMIN_URL}/admin/clients/dev-client-id 2>/dev/null)

if [ $? -eq 0 ] && echo "$CLIENT_INFO" | grep -q '"client_id":"dev-client-id"'; then
    print_success "Client verification successful"

    # Extract and display key configuration
    echo ""
    print_step "OAuth Client Configuration:"
    echo "  Client ID: dev-client-id"
    echo "  Client Name: Personal Management System (Development)"
    echo "  Redirect URI: http://localhost:3000/auth/callback"
    echo "  Grant Types: authorization_code, refresh_token"
    echo "  Scope: openid profile email"
    echo "  Skip Consent: true"
else
    print_warning "Client verification failed, but client may still work"
fi

# Test basic endpoints
print_step "Testing OAuth endpoints..."

# Test authorization endpoint
AUTH_URL="http://localhost:4444/oauth2/auth?client_id=dev-client-id&response_type=code&scope=openid%20profile%20email&redirect_uri=http://localhost:3000/auth/callback&state=test"

if curl -s -o /dev/null -w "%{http_code}" "$AUTH_URL" | grep -E "^(200|302)$" >/dev/null; then
    print_success "Authorization endpoint is working"
else
    print_warning "Authorization endpoint test inconclusive"
fi

print_success "OAuth provider initialization complete!"
echo ""
print_step "🔗 OAuth Configuration Summary:"
echo "  Authorization URL: http://localhost:4444/oauth2/auth"
echo "  Token URL: http://localhost:4444/oauth2/token"
echo "  Userinfo URL: http://localhost:4444/userinfo"
echo "  Admin URL: http://localhost:4445"
echo ""
print_step "🧪 Test the OAuth flow:"
echo "  1. Open http://localhost:3000/auth/login"
echo "  2. Click the OAuth login button"
echo "  3. Complete the authorization flow"
echo ""
