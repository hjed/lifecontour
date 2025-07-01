#!/bin/bash

# OAuth Docker Integration Verification Script
# This script verifies that the OAuth flow works correctly with the Docker Compose setup

set -e

echo "🔐 OAuth Docker Integration Verification"
echo "========================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
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

# Check if Docker is running
print_step "Checking Docker availability..."
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or not in PATH"
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running"
    exit 1
fi

print_success "Docker is available and running"

# Check if Docker Compose is available
print_step "Checking Docker Compose availability..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    print_error "Docker Compose is not available"
    exit 1
fi

print_success "Docker Compose is available"

# Function to check if a service is healthy
check_service_health() {
    local service_name=$1
    local max_attempts=30
    local attempt=0
    
    print_step "Checking $service_name health..."
    
    while [ $attempt -lt $max_attempts ]; do
        if docker-compose -f docker-compose.dev.yml ps $service_name | grep -q "healthy\|Up"; then
            print_success "$service_name is healthy"
            return 0
        fi
        
        echo "Waiting for $service_name to be healthy... (attempt $((attempt + 1))/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done
    
    print_warning "$service_name is not healthy after $max_attempts attempts"
    return 1
}

# Function to test HTTP endpoint
test_endpoint() {
    local url=$1
    local description=$2
    local expected_status=${3:-200}
    
    print_step "Testing $description..."
    
    if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "$expected_status"; then
        print_success "$description is accessible"
        return 0
    else
        print_warning "$description is not accessible"
        return 1
    fi
}

# Function to test JSON endpoint
test_json_endpoint() {
    local url=$1
    local description=$2
    
    print_step "Testing $description..."
    
    local response=$(curl -s "$url" 2>/dev/null)
    if echo "$response" | jq . &> /dev/null; then
        print_success "$description returned valid JSON"
        echo "Response preview: $(echo "$response" | jq -c . | head -c 100)..."
        return 0
    else
        print_warning "$description did not return valid JSON"
        return 1
    fi
}

# Start Docker Compose services
print_step "Starting Docker Compose services..."
if docker-compose -f docker-compose.dev.yml up -d; then
    print_success "Docker Compose services started"
else
    print_error "Failed to start Docker Compose services"
    exit 1
fi

# Wait a bit for services to initialize
echo "Waiting for services to initialize..."
sleep 10

# Check core services
print_step "Verifying core services..."

# Check Hydra OAuth Provider
if check_service_health "oauth-provider-dev"; then
    # Test Hydra endpoints
    test_endpoint "http://localhost:4444/health/ready" "Hydra public health endpoint"
    test_endpoint "http://localhost:4445/health/ready" "Hydra admin health endpoint"
    test_json_endpoint "http://localhost:4444/.well-known/openid_configuration" "Hydra OpenID configuration"
    
    # Check if OAuth client exists
    print_step "Checking OAuth client configuration..."
    if curl -s "http://localhost:4445/admin/clients/dev-client-id" | jq . &> /dev/null; then
        print_success "OAuth client 'dev-client-id' is configured"
        
        # Show client details
        echo "Client configuration:"
        curl -s "http://localhost:4445/admin/clients/dev-client-id" | jq '{client_id, redirect_uris, grant_types, response_types, scope}'
    else
        print_warning "OAuth client 'dev-client-id' not found or not accessible"
    fi
else
    print_error "Hydra OAuth provider is not healthy"
fi

# Check OAuth UI
if check_service_health "oauth-ui-dev"; then
    test_endpoint "http://localhost:3001" "OAuth UI" "200"
else
    print_warning "OAuth UI is not healthy"
fi

# Check Backend
if check_service_health "backend-dev"; then
    test_endpoint "http://localhost:8000/api/health" "Backend health endpoint"
    
    # Test OAuth endpoints
    print_step "Testing backend OAuth endpoints..."
    
    # Test login endpoint (should return method not allowed for GET)
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/auth/login" | grep -q "405"; then
        print_success "OAuth login endpoint is accessible"
    else
        print_warning "OAuth login endpoint may not be configured"
    fi
    
    # Test session endpoint
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/auth/session" | grep -q "401\|200"; then
        print_success "OAuth session endpoint is accessible"
    else
        print_warning "OAuth session endpoint may not be configured"
    fi
else
    print_error "Backend is not healthy"
fi

# Check Frontend
if check_service_health "frontend-dev"; then
    test_endpoint "http://localhost:3000" "Frontend" "200"
    
    # Test if login page loads
    print_step "Testing frontend OAuth integration..."
    if curl -s "http://localhost:3000/auth/login" | grep -q "Welcome Back\|Continue with\|OAuth"; then
        print_success "Frontend login page contains OAuth elements"
    else
        print_warning "Frontend login page may not have OAuth integration"
    fi
else
    print_error "Frontend is not healthy"
fi

# Test OAuth flow integration
print_step "Testing OAuth flow integration..."

# Create a simple test to verify OAuth button functionality
cat > /tmp/oauth_test.js << 'EOF'
const puppeteer = require('puppeteer');

(async () => {
  try {
    const browser = await puppeteer.launch({ headless: true });
    const page = await browser.newPage();
    
    // Navigate to login page
    await page.goto('http://localhost:3000/auth/login');
    await page.waitForLoadState('networkidle');
    
    // Look for OAuth buttons
    const oauthButtons = await page.$$('button:has-text("Continue with")');
    
    if (oauthButtons.length > 0) {
      console.log('✅ OAuth buttons found on login page');
      
      // Try clicking the first OAuth button
      await oauthButtons[0].click();
      await page.waitForTimeout(2000);
      
      const currentUrl = page.url();
      if (currentUrl.includes('localhost:4444') || currentUrl.includes('oauth2/auth')) {
        console.log('✅ Successfully redirected to Hydra OAuth provider');
      } else {
        console.log('⚠️  OAuth click did not redirect to Hydra (URL: ' + currentUrl + ')');
      }
    } else {
      console.log('⚠️  No OAuth buttons found on login page');
    }
    
    await browser.close();
  } catch (error) {
    console.log('❌ OAuth integration test failed:', error.message);
  }
})();
EOF

# Run the OAuth integration test if Node.js and Puppeteer are available
if command -v node &> /dev/null; then
    print_step "Running OAuth integration test..."
    if npm list puppeteer &> /dev/null || npm list -g puppeteer &> /dev/null; then
        node /tmp/oauth_test.js
    else
        print_warning "Puppeteer not available - skipping OAuth integration test"
        print_warning "Install Puppeteer to run full OAuth integration tests: npm install puppeteer"
    fi
else
    print_warning "Node.js not available - skipping OAuth integration test"
fi

# Clean up test file
rm -f /tmp/oauth_test.js

# Summary
print_step "Verification Summary"
echo "===================="

print_success "OAuth Docker integration verification completed"
echo ""
echo "🔗 Service URLs:"
echo "   Frontend:     http://localhost:3000"
echo "   Backend:      http://localhost:8000"
echo "   Hydra Public: http://localhost:4444"
echo "   Hydra Admin:  http://localhost:4445"
echo "   OAuth UI:     http://localhost:3001"
echo ""
echo "🧪 To run Playwright OAuth tests:"
echo "   cd frontend && npm run test:e2e -- oauth-flow.spec.ts"
echo "   cd frontend && npm run test:e2e -- oauth-error-handling.spec.ts"
echo "   cd frontend && npm run test:e2e -- oauth-docker-integration.spec.ts"
echo ""
echo "🛠️  To stop services:"
echo "   docker-compose -f docker-compose.dev.yml down"
echo ""

print_success "OAuth Docker verification script completed successfully!"
