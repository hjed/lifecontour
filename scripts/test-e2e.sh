#!/bin/bash

# E2E Test Runner Script
# Provides convenient commands for running Playwright e2e tests locally

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored output
print_status() {
    echo -e "${BLUE}[E2E]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[E2E]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[E2E]${NC} $1"
}

print_error() {
    echo -e "${RED}[E2E]${NC} $1"
}

# Help function
show_help() {
    echo "E2E Test Runner"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  setup     Set up Docker environment for e2e tests"
    echo "  test      Run Playwright e2e tests"
    echo "  cleanup   Clean up Docker environment"
    echo "  status    Show status of Docker services"
    echo "  logs      Show logs from Docker services"
    echo "  help      Show this help message"
    echo ""
    echo "Options:"
    echo "  --headed     Run tests in headed mode (visible browser)"
    echo "  --debug      Run tests in debug mode"
    echo "  --ui         Run tests with Playwright UI"
    echo "  --cleanup    Force cleanup after tests"
    echo "  --browser    Specify browser project (e.g., --browser chromium)"
    echo "  --chromium   Run tests in Chromium only"
    echo "  --firefox    Run tests in Firefox only"
    echo "  --mobile     Run tests in Mobile Chrome only"
    echo ""
    echo "Examples:"
    echo "  $0 setup                    # Set up environment"
    echo "  $0 test                     # Run all tests in all browsers"
    echo "  $0 test --chromium          # Run tests in Chromium only"
    echo "  $0 test --firefox           # Run tests in Firefox only"
    echo "  $0 test --mobile            # Run tests in Mobile Chrome only"
    echo "  $0 test --headed            # Run tests with visible browser"
    echo "  $0 test --ui                # Run tests with Playwright UI"
    echo "  $0 test auth/login.spec.ts  # Run specific test file"
    echo "  $0 cleanup                  # Clean up environment"
}

# Check if we're in the right directory
check_directory() {
    if [[ ! -f "docker-compose.test.yml" ]]; then
        print_error "Must be run from project root directory"
        exit 1
    fi
}

# Setup Docker environment
setup_environment() {
    print_status "Setting up Docker environment for e2e tests..."

    # Stop any existing containers
    print_status "Stopping existing containers..."
    docker compose -f docker-compose.test.yml down --remove-orphans || true

    # Start services
    print_status "Starting Docker services..."
    docker compose -f docker-compose.test.yml up -d --build

    # Verify services are ready
    print_status "Verifying services..."

    # Check backend health
    for i in {1..30}; do
        if curl -s http://localhost:8001/api/health > /dev/null; then
            print_success "Backend is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_error "Backend failed to start"
            exit 1
        fi
        sleep 2
    done

    # Check OAuth provider
    for i in {1..30}; do
        if curl -s http://localhost:4446/.well-known/openid_configuration > /dev/null; then
            print_success "OAuth provider is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            print_error "OAuth provider failed to start"
            exit 1
        fi
        sleep 2
    done

    print_success "Environment setup complete!"
}

# Run Playwright tests
run_tests() {
    local test_args=()
    local playwright_args=()

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --headed)
                playwright_args+=("--headed")
                shift
                ;;
            --debug)
                playwright_args+=("--debug")
                shift
                ;;
            --ui)
                playwright_args+=("--ui")
                shift
                ;;
            --cleanup)
                export CLEANUP_AFTER_TESTS=true
                shift
                ;;
            --browser)
                playwright_args+=("--project=$2")
                shift 2
                ;;
            --chromium)
                playwright_args+=("--project=chromium")
                shift
                ;;
            --firefox)
                playwright_args+=("--project=firefox")
                shift
                ;;
            --mobile)
                playwright_args+=("--project=Mobile Chrome")
                shift
                ;;
            *.spec.ts)
                test_args+=("$1")
                shift
                ;;
            *)
                test_args+=("$1")
                shift
                ;;
        esac
    done

    print_status "Running Playwright e2e tests..."

    cd frontend

    # Install Playwright browsers if needed
    if [[ ! -d ~/.cache/ms-playwright ]]; then
        print_status "Installing Playwright browsers..."
        pnpm exec playwright install chromium firefox
    fi

    # Run tests
    if [[ ${#test_args[@]} -gt 0 ]]; then
        print_status "Running specific tests: ${test_args[*]}"
        pnpm exec playwright test "${test_args[@]}" "${playwright_args[@]}"
    else
        print_status "Running all tests"
        pnpm exec playwright test "${playwright_args[@]}"
    fi

    cd ..
}

# Cleanup environment
cleanup_environment() {
    print_status "Cleaning up Docker environment..."
    docker compose -f docker-compose.test.yml down --volumes --remove-orphans
    print_success "Cleanup complete!"
}

# Show service status
show_status() {
    print_status "Docker service status:"
    docker compose -f docker-compose.test.yml ps
}

# Show service logs
show_logs() {
    local service=${1:-}
    if [[ -n "$service" ]]; then
        print_status "Showing logs for service: $service"
        docker compose -f docker-compose.test.yml logs --tail=50 -f "$service"
    else
        print_status "Showing logs for all services:"
        docker compose -f docker-compose.test.yml logs --tail=50
    fi
}

# Main script logic
main() {
    check_directory

    case "${1:-help}" in
        setup)
            setup_environment
            ;;
        test)
            shift
            run_tests "$@"
            ;;
        cleanup)
            cleanup_environment
            ;;
        status)
            show_status
            ;;
        logs)
            shift
            show_logs "$@"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
