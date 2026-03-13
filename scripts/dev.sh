#!/bin/bash

# Development script for Personal Management System
# Provides easy commands for common development tasks

set -e

# Load workspace environment variables for docker isolation (opt-in)
if [[ "${USE_WORKSPACE_ENV:-0}" == "1" ]] && [[ -f "scripts/workspace_env.py" ]]; then
    eval "$(python3 scripts/workspace_env.py export)"
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    local msg="$1"
    echo -e "${BLUE}[INFO]${NC} $msg"
    return 0
}

log_success() {
    local msg="$1"
    echo -e "${GREEN}[SUCCESS]${NC} $msg"
    return 0
}

log_warning() {
    local msg="$1"
    echo -e "${YELLOW}[WARNING]${NC} $msg"
    return 0
}

log_error() {
    local msg="$1"
    echo -e "${RED}[ERROR]${NC} $msg" >&2
    return 0
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Setup function
setup() {
    log_info "Setting up Personal Management System development environment..."

    # Check prerequisites
    if ! command_exists "uv"; then
        log_error "UV is not installed. Please install UV for Python dependency management."
        exit 1
    fi

    if ! command_exists "pnpm"; then
        log_error "pnpm is not installed. Please install pnpm for frontend dependency management."
        exit 1
    fi

    if ! command_exists "docker"; then
        log_warning "Docker is not installed. You'll need Docker for the full development environment."
    fi

    # Setup backend
    log_info "Setting up backend dependencies..."
    cd backend
    if [ ! -f ".env" ]; then
        cp .env.example .env
        log_info "Created backend .env file from example. Please configure it."
    fi

    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        log_info "Creating Python virtual environment..."
        uv venv
    fi

    # Install dependencies
    uv pip install -e .[dev]
    cd ..

    # Setup frontend
    log_info "Setting up frontend dependencies..."
    cd frontend
    if [ ! -f ".env.local" ]; then
        cp .env.example .env.local
        log_info "Created frontend .env.local file from example. Please configure it."
    fi
    pnpm install
    cd ..

    log_success "Development environment setup complete!"
    log_info "Next steps:"
    log_info "1. Configure your .env files"
    log_info "2. Start the database: docker compose up database"
    log_info "3. Run migrations: cd backend && alembic upgrade head"
    log_info "4. Start development: ./scripts/dev.sh start"
}

# Start development servers (local mode)
start() {
    log_info "Starting development servers (local mode)..."
    log_warning "This requires PostgreSQL and MeiliSearch to be running locally."
    log_info "For a complete Docker environment, use: ./scripts/dev.sh docker-start"

    # Start backend
    log_info "Starting backend server..."
    cd backend
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    cd ..

    # Start frontend
    log_info "Starting frontend server..."
    cd frontend
    pnpm dev &
    FRONTEND_PID=$!
    cd ..

    log_success "Development servers started!"
    log_info "Backend: http://localhost:8000"
    log_info "Frontend: http://localhost:3000"
    log_info "API Docs: http://localhost:8000/api/docs"

    # Wait for interrupt
    trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT
    wait
}

# Start complete Docker development environment
docker_start() {
    log_info "Starting complete Docker development environment..."

    # Check if Docker is available
    if ! command_exists "docker"; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    # Copy development environment file
    if [ ! -f ".env.dev" ]; then
        log_error ".env.dev file not found. Please ensure it exists."
        exit 1
    fi

    # Start all services with dev profile (default)
    log_info "Starting all services with Docker Compose (dev profile)..."
    docker compose --profile dev --env-file .env.dev up -d

    log_success "Docker development environment started!"
    log_info ""
    log_info "🌐 Service URLs:"
    log_info "  Frontend:        http://localhost:3000"
    log_info "  Backend API:     http://localhost:8000"
    log_info "  API Docs:        http://localhost:8000/api/docs"
    log_info "  OAuth Provider:  http://localhost:3001"
    log_info "  Jaeger UI:       http://localhost:16686"
    log_info "  MeiliSearch:     http://localhost:7700"
    log_info "  PostgreSQL:      localhost:5432"
    log_info ""
    log_info "📋 Test OAuth Credentials:"
    log_info "  Email: dev@example.com"
    log_info "  Password: password123"
    log_info ""
    log_info "Use './scripts/dev.sh docker-logs' to view logs"
    log_info "Use './scripts/dev.sh docker-stop' to stop all services"
}

# Stop Docker development environment
docker_stop() {
    log_info "Stopping Docker development environment..."
    docker compose --profile dev down
    log_success "Docker development environment stopped!"
}

# Show Docker logs
docker_logs() {
    if [ -n "$2" ]; then
        # Show logs for specific service
        log_info "Showing logs for service: $2"
        docker compose --profile dev logs -f "$2"
    else
        # Show logs for all services
        log_info "Showing logs for all services (use Ctrl+C to exit)..."
        docker compose --profile dev logs -f
    fi
}

# Restart specific Docker service
docker_restart() {
    if [ -z "$2" ]; then
        log_error "Please specify a service name to restart"
        log_info "Available services: database, redis, meilisearch, jaeger, oauth-provider, oauth-login-consent, backend, frontend, google-worker"
        exit 1
    fi

    log_info "Restarting Docker service: $2"
    docker compose --profile dev restart "$2"
    log_success "Service $2 restarted!"
}

# Show Docker status
docker_status() {
    log_info "Docker development environment status:"
    docker compose --profile dev ps
}

# Test Docker environment
docker_test() {
    log_info "Testing Docker development environment..."
    if [ ! -f "scripts/test-docker-env.sh" ]; then
        log_error "Test script not found: scripts/test-docker-env.sh"
        exit 1
    fi

    ./scripts/test-docker-env.sh
}

# Rebuild Docker images (development)
docker_rebuild() {
    log_info "Rebuilding Docker images for development environment..."

    # Check if Docker is available
    if ! command_exists "docker"; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    # Stop services first to avoid conflicts
    log_info "Stopping existing services..."
    docker compose --profile dev down

    # Rebuild images with no cache
    log_info "Rebuilding backend and frontend images (no cache)..."
    docker compose --profile dev build --no-cache backend frontend

    log_success "Docker images rebuilt successfully!"
    log_info "Use './scripts/dev.sh docker-start' to start the services with new images"
}

# Rebuild Docker images (production)
docker_rebuild_prod() {
    log_info "Rebuilding Docker images for production environment..."

    # Check if Docker is available
    if ! command_exists "docker"; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    # Stop services first to avoid conflicts
    log_info "Stopping existing services..."
    docker compose --profile prod down

    # Rebuild images with no cache
    log_info "Rebuilding backend, frontend, nginx, and google-worker images (no cache)..."
    docker compose --profile prod build --no-cache backend frontend nginx google-worker

    log_success "Production Docker images rebuilt successfully!"
    log_info "Use 'docker compose --profile prod up -d' to start the services with new images"
}

# Rebuild specific Docker service
docker_rebuild_service() {
    if [ -z "$2" ]; then
        log_error "Please specify a service name to rebuild"
        log_info "Services: backend, frontend, nginx, google-worker"
        exit 1
    fi

    local service="$2"
    local profile="${3:-dev}"  # Default to dev profile

    log_info "Rebuilding service: $service (profile: $profile)"

    # Check if Docker is available
    if ! command_exists "docker"; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    # Stop the specific service
    log_info "Stopping service: $service"
    docker compose --profile "$profile" stop "$service"

    # Rebuild the service with no cache
    log_info "Rebuilding service: $service (no cache)..."
    docker compose --profile "$profile" build --no-cache "$service"

    # Restart the service
    log_info "Starting service: $service"
    docker compose --profile "$profile" up -d "$service"

    log_success "Service $service rebuilt and restarted successfully!"
}

# Run tests
test() {
    log_info "Running tests..."

    # Backend tests
    log_info "Running backend tests..."
    cd backend
    uv run pytest
    cd ..

    # Core shared tests
    log_info "Running core_shared tests..."
    cd core_shared
    uv run pytest
    cd ..

    # Frontend tests
    log_info "Running frontend tests..."
    cd frontend
    pnpm test
    cd ..

    log_success "All tests completed!"
}

# Lint code
lint() {
    log_info "Running linters..."

    # Backend linting
    log_info "Linting backend..."
    cd backend
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy .
    cd ..

    # Core shared linting
    log_info "Linting core_shared..."
    cd core_shared
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy .
    cd ..

    # Frontend linting
    log_info "Linting frontend..."
    cd frontend
    pnpm lint
    pnpm type-check
    pnpm format:check
    cd ..

    log_success "Linting completed!"
}

# Fix linting issues
lint_fix() {
    log_info "Fixing linting issues..."

    # Backend
    cd backend
    uv run ruff check . --fix
    uv run ruff format .
    cd ..

    # Core shared
    cd core_shared
    uv run ruff check . --fix
    uv run ruff format .
    cd ..

    # Frontend
    cd frontend
    pnpm lint:fix
    pnpm format
    cd ..

    log_success "Linting fixes applied!"
}

# Run pre-commit hooks
precommit() {
    log_info "Running pre-commit hooks..."

    cd backend
    if ! uv run pre-commit --version >/dev/null 2>&1; then
        log_error "Pre-commit not found. Run './scripts/dev.sh setup' first."
        exit 1
    fi

    uv run pre-commit run --all-files
    cd ..

    log_success "Pre-commit hooks completed!"
}

# Show help
help() {
    echo "Personal Management System Development Script"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Local Development Commands:"
    echo "  setup           Set up development environment"
    echo "  start           Start development servers (requires local PostgreSQL/MeiliSearch)"
    echo "  test            Run all tests"
    echo "  lint            Run linters"
    echo "  lint-fix        Fix linting issues"
    echo "  precommit       Run pre-commit hooks"
    echo ""
    echo "Docker Development Commands:"
    echo "  docker-start         Start complete Docker development environment"
    echo "  docker-stop          Stop Docker development environment"
    echo "  docker-logs          Show logs for all services (or specify service name)"
    echo "  docker-restart       Restart specific Docker service"
    echo "  docker-status        Show status of Docker services"
    echo "  docker-test          Test all Docker services are working correctly"
    echo "  docker-rebuild       Rebuild all Docker images for development (no cache)"
    echo "  docker-rebuild-prod  Rebuild all Docker images for production (no cache)"
    echo "  docker-rebuild-service  Rebuild specific Docker service (specify service name)"
    echo ""
    echo "Examples:"
    echo "  $0 docker-start                    # Start full Docker environment"
    echo "  $0 docker-logs backend-dev         # Show backend logs only"
    echo "  $0 docker-restart backend-dev      # Restart backend service"
    echo "  $0 docker-rebuild                  # Rebuild all dev images (fresh build)"
    echo "  $0 docker-rebuild-service backend-dev  # Rebuild only backend service"
    echo ""
    echo "Service URLs (when using docker-start):"
    echo "  Frontend:        http://localhost:3000"
    echo "  Backend API:     http://localhost:8000/api/docs"
    echo "  OAuth Provider:  http://localhost:3001"
    echo "  Jaeger UI:       http://localhost:16686"
    echo "  MeiliSearch:     http://localhost:7700"
    echo ""
}

# Main script logic
case "${1:-help}" in
    setup)
        setup
        ;;
    start)
        start
        ;;
    docker-start)
        docker_start
        ;;
    docker-stop)
        docker_stop
        ;;
    docker-logs)
        docker_logs "$@"
        ;;
    docker-restart)
        docker_restart "$@"
        ;;
    docker-status)
        docker_status
        ;;
    docker-test)
        docker_test
        ;;
    docker-rebuild)
        docker_rebuild
        ;;
    docker-rebuild-prod)
        docker_rebuild_prod
        ;;
    docker-rebuild-service)
        docker_rebuild_service "$@"
        ;;
    test)
        test
        ;;
    lint)
        lint
        ;;
    lint-fix)
        lint_fix
        ;;
    precommit)
        precommit
        ;;
    help)
        help
        ;;
    *)
        log_error "Unknown command: $1"
        help
        exit 1
        ;;
esac
