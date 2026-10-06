# Lifecontour Development Script (PowerShell)
# Provides easy commands for common development tasks on Windows

param(
    [Parameter(Position=0)]
    [string]$Command = "help",

    [Parameter(Position=1)]
    [string]$ServiceName = ""
)

# Load workspace environment variables for docker isolation when running tests
if ($Command -eq "test" -and (Test-Path "scripts\workspace_env.py")) {
    $env_vars = python scripts\workspace_env.py ps1
    $env_vars | ForEach-Object { Invoke-Expression $_ }
}

# Colors for output
$Colors = @{
    Red = "Red"
    Green = "Green"
    Yellow = "Yellow"
    Blue = "Blue"
    White = "White"
}

# Helper functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor $Colors.Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor $Colors.Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor $Colors.Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor $Colors.Red
}

# Check if command exists
function Test-Command {
    param([string]$CommandName)
    return (Get-Command $CommandName -ErrorAction SilentlyContinue) -ne $null
}

# Rebuild Docker images (development)
function Invoke-DockerRebuild {
    Write-Info "Rebuilding Docker images for development environment..."

    # Check if Docker is available
    if (-not (Test-Command "docker")) {
        Write-Error "Docker is not installed. Please install Docker first."
        exit 1
    }

    # Stop services first to avoid conflicts
    Write-Info "Stopping existing services..."
    docker compose --profile dev down

    # Rebuild images with no cache
    Write-Info "Rebuilding backend and frontend images (no cache)..."
    docker compose --profile dev build --no-cache backend frontend

    Write-Success "Docker images rebuilt successfully!"
    Write-Info "Use '.\scripts\dev.ps1 docker-start' to start the services with new images"
}

# Rebuild Docker images (production)
function Invoke-DockerRebuildProd {
    Write-Info "Rebuilding Docker images for production environment..."

    # Check if Docker is available
    if (-not (Test-Command "docker")) {
        Write-Error "Docker is not installed. Please install Docker first."
        exit 1
    }

    # Stop services first to avoid conflicts
    Write-Info "Stopping existing services..."
    docker compose --profile prod down

    # Rebuild images with no cache
    Write-Info "Rebuilding backend, frontend, nginx, and google-worker images (no cache)..."
    docker compose --profile prod build --no-cache backend frontend nginx google-worker

    Write-Success "Production Docker images rebuilt successfully!"
    Write-Info "Use 'docker compose --profile prod up -d' to start the services with new images"
}

# Rebuild specific Docker service
function Invoke-DockerRebuildService {
    param([string]$Service, [string]$Profile = "dev")

    if ([string]::IsNullOrEmpty($Service)) {
        Write-Error "Please specify a service name to rebuild"
        Write-Info "Services: backend, frontend, nginx, google-worker"
        exit 1
    }

    Write-Info "Rebuilding service: $Service (profile: $Profile)"

    # Check if Docker is available
    if (-not (Test-Command "docker")) {
        Write-Error "Docker is not installed. Please install Docker first."
        exit 1
    }

    # Stop the specific service
    Write-Info "Stopping service: $Service"
    docker compose --profile $Profile stop $Service

    # Rebuild the service with no cache
    Write-Info "Rebuilding service: $Service (no cache)..."
    docker compose --profile $Profile build --no-cache $Service

    # Restart the service
    Write-Info "Starting service: $Service"
    docker compose --profile $Profile up -d $Service

    Write-Success "Service $Service rebuilt and restarted successfully!"
}

# Start complete Docker development environment
function Invoke-DockerStart {
    Write-Info "Starting Docker development environment..."

    # Check if Docker is available
    if (-not (Test-Command "docker")) {
        Write-Error "Docker is not installed. Please install Docker first."
        exit 1
    }

    # Start all services with dev profile (default)
    Write-Info "Starting all services with Docker Compose (dev profile)..."
    docker compose --profile dev --env-file .env.dev up -d

    Write-Success "Docker development environment started!"
    Write-Info ""
    Write-Info "🌐 Service URLs:"
    Write-Info "  Frontend:        http://localhost:3000"
    Write-Info "  Backend API:     http://localhost:8000"
    Write-Info "  API Docs:        http://localhost:8000/api/docs"
    Write-Info "  OAuth Provider:  http://localhost:3001"
    Write-Info "  Jaeger UI:       http://localhost:16686"
    Write-Info "  MeiliSearch:     http://localhost:7700"
    Write-Info "  PostgreSQL:      localhost:5432"
    Write-Info ""
    Write-Info "Use '.\scripts\dev.ps1 docker-stop' to stop all services"
}

# Stop Docker development environment
function Invoke-DockerStop {
    Write-Info "Stopping Docker development environment..."
    docker compose --profile dev down
    Write-Success "Docker development environment stopped!"
}

# Show help
function Show-Help {
    Write-Host "Lifecontour Development Script (PowerShell)" -ForegroundColor $Colors.White
    Write-Host ""
    Write-Host "Usage: .\scripts\dev.ps1 [command] [options]" -ForegroundColor $Colors.White
    Write-Host ""
    Write-Host "Docker Development Commands:" -ForegroundColor $Colors.White
    Write-Host "  docker-start         Start complete Docker development environment"
    Write-Host "  docker-stop          Stop Docker development environment"
    Write-Host "  docker-rebuild       Rebuild all Docker images for development (no cache)"
    Write-Host "  docker-rebuild-prod  Rebuild all Docker images for production (no cache)"
    Write-Host "  docker-rebuild-service  Rebuild specific Docker service (specify service name)"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor $Colors.White
    Write-Host "  .\scripts\dev.ps1 docker-start                    # Start full Docker environment"
    Write-Host "  .\scripts\dev.ps1 docker-rebuild                  # Rebuild all dev images (fresh build)"
    Write-Host "  .\scripts\dev.ps1 docker-rebuild-service backend-dev  # Rebuild only backend service"
    Write-Host ""
    Write-Host "Service URLs (when using docker-start):" -ForegroundColor $Colors.White
    Write-Host "  Frontend:        http://localhost:3000"
    Write-Host "  Backend API:     http://localhost:8000/api/docs"
    Write-Host "  OAuth Provider:  http://localhost:3001"
    Write-Host "  Jaeger UI:       http://localhost:16686"
    Write-Host "  MeiliSearch:     http://localhost:7700"
    Write-Host ""
}

# Main script logic
switch ($Command.ToLower()) {
    "docker-start" {
        Invoke-DockerStart
    }
    "docker-stop" {
        Invoke-DockerStop
    }
    "docker-rebuild" {
        Invoke-DockerRebuild
    }
    "docker-rebuild-prod" {
        Invoke-DockerRebuildProd
    }
    "docker-rebuild-service" {
        Invoke-DockerRebuildService -Service $ServiceName
    }
    "help" {
        Show-Help
    }
    default {
        Write-Error "Unknown command: $Command"
        Show-Help
        exit 1
    }
}
