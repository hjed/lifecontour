#!/bin/sh

# OAuth Provider Initialization Script for Testing
# This script creates the OAuth client automatically for testing environments

set -e

echo "🧪 Starting OAuth provider initialization for testing..."

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
max_attempts=60  # Increased timeout for test environment
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if curl -f -s http://localhost:4445/health/ready >/dev/null 2>&1; then
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
    print_error "Check Hydra logs: docker logs pms-oauth-test"
    exit 1
fi

# Additional wait to ensure Hydra is fully initialized
sleep 3

# Check if client already exists
print_step "Checking if OAuth client already exists..."
if curl -f -s http://localhost:4445/admin/clients/test-client-id >/dev/null 2>&1; then
    print_warning "OAuth client already exists, removing it first..."
    if curl -X DELETE -s http://localhost:4445/admin/clients/test-client-id >/dev/null 2>&1; then
        print_success "Existing client removed"
        sleep 2  # Wait for deletion to complete
    else
        print_warning "Failed to remove existing client, continuing anyway..."
    fi
fi

# Create OAuth client with comprehensive configuration for testing
print_step "Creating OAuth client for testing..."

CLIENT_CONFIG='{
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "redirect_uris": ["http://localhost:3000/auth/callback"],
    "post_logout_redirect_uris": ["http://localhost:3000/"],
    "scope": "openid profile email",
    "audience": [],
    "skip_consent": true,
    "skip_logout_consent": true,
    "client_name": "Personal Management System (Testing)",
    "client_uri": "http://localhost:3000",
    "logo_uri": "",
    "policy_uri": "",
    "tos_uri": "",
    "token_endpoint_auth_method": "client_secret_post",
    "userinfo_signed_response_alg": "none",
    "subject_type": "public"
}'

if curl -X POST http://localhost:4445/admin/clients \
    -H "Content-Type: application/json" \
    -d "$CLIENT_CONFIG" \
    -f -s >/dev/null 2>&1; then
    print_success "OAuth client created successfully!"
else
    print_error "Failed to create OAuth client"
    print_error "Response from Hydra:"
    curl -X POST http://localhost:4445/admin/clients \
        -H "Content-Type: application/json" \
        -d "$CLIENT_CONFIG" 2>&1 || true
    exit 1
fi

# Verify client configuration
print_step "Verifying OAuth client configuration..."
CLIENT_INFO=$(curl -s http://localhost:4445/admin/clients/test-client-id 2>/dev/null)

if [ $? -eq 0 ] && echo "$CLIENT_INFO" | grep -q '"client_id":"test-client-id"'; then
    print_success "Client verification successful"
    
    # Extract and display key configuration
    echo ""
    print_step "OAuth Client Configuration (Testing):"
    echo "  Client ID: test-client-id"
    echo "  Client Name: Personal Management System (Testing)"
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
AUTH_URL="http://localhost:4446/oauth2/auth?client_id=test-client-id&response_type=code&scope=openid%20profile%20email&redirect_uri=http://localhost:3000/auth/callback&state=test"

if curl -s -o /dev/null -w "%{http_code}" "$AUTH_URL" | grep -E "^(200|302)$" >/dev/null; then
    print_success "Authorization endpoint is working"
else
    print_warning "Authorization endpoint test inconclusive"
fi

print_success "OAuth provider initialization complete for testing!"
echo ""
print_step "🔗 OAuth Configuration Summary (Testing):"
echo "  Authorization URL: http://localhost:4446/oauth2/auth"
echo "  Token URL: http://localhost:4446/oauth2/token"
echo "  Userinfo URL: http://localhost:4446/userinfo"
echo "  Admin URL: http://localhost:4447"
echo ""
print_step "🧪 Test the OAuth flow:"
echo "  1. Run tests: npm run test:e2e -- oauth-flow.spec.ts"
echo "  2. Or manually test at http://localhost:3000/auth/login"
echo ""
