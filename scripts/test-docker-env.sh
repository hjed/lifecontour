#!/bin/bash

# Test script for Docker development environment
# Verifies that all services are running and accessible

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Test function
test_service() {
    local name=$1
    local url=$2
    local expected_status=${3:-200}

    log_info "Testing $name at $url..."

    if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "$expected_status"; then
        log_success "$name is responding correctly"
        return 0
    else
        log_error "$name is not responding correctly"
        return 1
    fi
}

# Test JSON endpoint
test_json_service() {
    local name=$1
    local url=$2

    log_info "Testing $name JSON API at $url..."

    if curl -s "$url" | jq . > /dev/null 2>&1; then
        log_success "$name JSON API is responding correctly"
        return 0
    else
        log_error "$name JSON API is not responding correctly"
        return 1
    fi
}

# Main test function
main() {
    log_info "🧪 Testing Docker Development Environment"
    echo ""

    # Check if Docker Compose is running
    log_info "Checking Docker Compose services..."
    if ! docker compose -f docker-compose.dev.yml ps | grep -q "Up"; then
        log_error "Docker Compose services are not running!"
        log_info "Start them with: ./scripts/dev.sh docker-start"
        exit 1
    fi

    log_success "Docker Compose services are running"
    echo ""

    # Test each service
    local failed=0

    # Test PostgreSQL
    log_info "Testing PostgreSQL connection..."
    if docker exec pms-postgres-dev pg_isready -U dev_user -d personal_management_dev > /dev/null 2>&1; then
        log_success "PostgreSQL is ready"
    else
        log_error "PostgreSQL is not ready"
        ((failed++))
    fi

    # Test MeiliSearch
    if test_json_service "MeiliSearch" "http://localhost:7700/health"; then
        :
    else
        ((failed++))
    fi

    # Test Jaeger
    if test_service "Jaeger UI" "http://localhost:16686" "200"; then
        :
    else
        ((failed++))
    fi

    # Test OAuth Provider
    if test_json_service "OAuth Provider" "http://localhost:4444/.well-known/openid_configuration"; then
        :
    else
        ((failed++))
    fi

    # Test OAuth UI
    if test_service "OAuth UI" "http://localhost:3001" "200"; then
        :
    else
        ((failed++))
    fi

    # Test Backend API
    if test_json_service "Backend API" "http://localhost:8000/api/health"; then
        :
    else
        ((failed++))
    fi

    # Test Backend API Docs
    if test_service "Backend API Docs" "http://localhost:8000/api/docs" "200"; then
        :
    else
        ((failed++))
    fi

    # Test Frontend (might take longer to start)
    log_info "Testing Frontend (may take a moment to start)..."
    local frontend_attempts=0
    while [ $frontend_attempts -lt 10 ]; do
        if curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000" | grep -q "200"; then
            log_success "Frontend is responding correctly"
            break
        else
            ((frontend_attempts++))
            if [ $frontend_attempts -eq 10 ]; then
                log_error "Frontend is not responding correctly after 10 attempts"
                ((failed++))
            else
                log_info "Frontend not ready yet, waiting... (attempt $frontend_attempts/10)"
                sleep 3
            fi
        fi
    done

    echo ""

    # Summary
    if [ $failed -eq 0 ]; then
        log_success "🎉 All services are running correctly!"
        echo ""
        log_info "🌐 Service URLs:"
        log_info "  Frontend:        http://localhost:3000"
        log_info "  Backend API:     http://localhost:8000/api/docs"
        log_info "  OAuth Provider:  http://localhost:3001"
        log_info "  Jaeger UI:       http://localhost:16686"
        log_info "  MeiliSearch:     http://localhost:7700"
        echo ""
        log_info "🔐 Test OAuth Credentials:"
        log_info "  Email: dev@example.com"
        log_info "  Password: password123"
        echo ""
        log_info "Ready for development! 🚀"
    else
        log_error "❌ $failed service(s) failed tests"
        log_info "Check logs with: ./scripts/dev.sh docker-logs"
        exit 1
    fi
}

# Check if jq is available
if ! command -v jq >/dev/null 2>&1; then
    log_warning "jq is not installed. JSON API tests will be skipped."
    log_info "Install jq for better testing: sudo apt-get install jq (Ubuntu/Debian) or brew install jq (macOS)"
fi

# Run main function
main
