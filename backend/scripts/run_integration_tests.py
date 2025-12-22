#!/usr/bin/env python3
"""Script to run integration tests with Docker PostgreSQL."""

import subprocess
import sys
import time
from pathlib import Path


def get_docker_compose_cmd() -> list[str]:
    """Get the appropriate docker compose command."""
    # Try docker compose first (plugin version - preferred in CI)
    try:
        result = subprocess.run(
            ["docker", "compose", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        if "Docker Compose" in result.stdout:
            return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Try docker-compose (standalone version)
    try:
        result = subprocess.run(
            ["docker-compose", "--version"], check=True, capture_output=True, text=True
        )
        if "docker-compose" in result.stdout:
            return ["docker-compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Default to docker compose (newer version)
    return ["docker", "compose"]


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | subprocess.CalledProcessError:
    """Run a command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, cwd=cwd, check=check, capture_output=True, text=True, env=env
        )
        if result.stdout:
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        if check:
            sys.exit(1)
        return e


def check_docker() -> bool:
    """Check if Docker is available."""
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)

        # Check which docker compose command is available
        docker_compose_cmd = get_docker_compose_cmd()
        if docker_compose_cmd == ["docker-compose"]:
            print("✓ Docker and Docker Compose (standalone) are available")
        else:
            print("✓ Docker and Docker Compose (plugin) are available")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("✗ Docker or Docker Compose not found")
        print("Please install Docker and Docker Compose to run integration tests")
        return False


def start_test_services() -> bool:
    """Start the test database and MeiliSearch containers."""
    print("Starting test services...")

    # Check if containers are already running
    postgres_result = run_command(
        [
            "docker",
            "ps",
            "--filter",
            "name=pms-postgres",
            "--format",
            "{{.Names}}",
        ],
        check=False,
    )

    meilisearch_result = run_command(
        [
            "docker",
            "ps",
            "--filter",
            "name=pms-meilisearch",
            "--format",
            "{{.Names}}",
        ],
        check=False,
    )

    postgres_running = "pms-postgres" in postgres_result.stdout
    meilisearch_running = "pms-meilisearch" in meilisearch_result.stdout

    if postgres_running and meilisearch_running:
        print("✓ Test services already running")
        return True

    # Start the containers (run from project root)
    docker_compose_cmd = get_docker_compose_cmd()
    project_root = Path(__file__).parent.parent.parent
    run_command(
        docker_compose_cmd
        + ["--profile", "test-backend", "--env-file", ".env.test", "up", "-d"],
        cwd=project_root,
    )

    # Wait for services to be ready
    print("Waiting for test services to be ready...")

    # Wait for database
    print("  Checking database...")
    max_retries = 30
    for i in range(max_retries):
        # Get the actual container name
        container_result = run_command(
            [
                "docker",
                "ps",
                "--filter",
                "name=pms-postgres",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )

        if not container_result.stdout.strip():
            print(f"    Container not found... ({i + 1}/{max_retries})")
            time.sleep(1)
            continue

        container_name = container_result.stdout.strip()
        result = run_command(
            [
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-U",
                "postgres",
            ],
            check=False,
        )
        if result.returncode == 0:
            print("  ✓ Test database is ready")
            break

        time.sleep(1)
        print(f"    Waiting... ({i + 1}/{max_retries})")
    else:
        print("  ✗ Test database failed to start within timeout")
        return False

    # Wait for MeiliSearch
    print("  Checking MeiliSearch...")
    for i in range(max_retries):
        try:
            result = run_command(
                ["curl", "-f", "http://localhost:7701/health"],
                check=False,
            )
            if result.returncode == 0:
                print("  ✓ Test MeiliSearch is ready")
                break
        except Exception:
            pass

        time.sleep(1)
        print(f"    Waiting... ({i + 1}/{max_retries})")
    else:
        print("  ✗ Test MeiliSearch failed to start within timeout")
        return False

    print("✓ All test services are ready")
    time.sleep(2)  # Give services a bit more time
    return True


def stop_test_services() -> None:
    """Stop the test services containers."""
    print("Stopping test services...")
    docker_compose_cmd = get_docker_compose_cmd()
    project_root = Path(__file__).parent.parent.parent
    run_command(
        docker_compose_cmd + ["--profile", "test-backend", "down", "-v"],
        cwd=project_root,
        check=False,
    )
    print("✓ Test services stopped")


def run_tests() -> bool:
    """Run the integration tests."""
    print("Running integration tests...")

    # Set environment variables for test MeiliSearch configuration
    import os

    test_env = os.environ.copy()
    test_env.update(
        {
            "MEILISEARCH_URL": "http://localhost:7701",
            "MEILISEARCH_API_KEY": "test_master_key",
            "DATABASE_URL": "postgresql://postgres:postgres@localhost:5433/personal_management_test",
        }
    )

    # Run only integration tests
    cmd = [
        "python",
        "-m",
        "pytest",
        "tests/integration/",
        "-v",
        "--tb=short",
        "-x",  # Stop on first failure
    ]

    result = run_command(cmd, check=False, env=test_env)
    return result.returncode == 0


def main() -> None:
    """Main function."""
    print("🧪 Integration Test Runner")
    print("=" * 50)

    # Change to backend directory
    backend_dir = Path(__file__).parent.parent
    print(f"Working directory: {backend_dir}")

    # Check prerequisites
    if not check_docker():
        sys.exit(1)

    try:
        # Start services
        if not start_test_services():
            sys.exit(1)

        # Run tests
        print("\n" + "=" * 50)
        success = run_tests()

        if success:
            print("\n✅ All integration tests passed!")
        else:
            print("\n❌ Some integration tests failed!")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)
    finally:
        # Always try to stop the services
        print("\n" + "=" * 50)
        stop_test_services()


if __name__ == "__main__":
    main()
