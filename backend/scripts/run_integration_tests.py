#!/usr/bin/env python3
"""Script to run integration tests with Docker PostgreSQL."""

import subprocess
import sys
import time
from pathlib import Path


def run_command(cmd, cwd=None, check=True):
    """Run a command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
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


def check_docker():
    """Check if Docker is available."""
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
        subprocess.run(["docker", "compose", "--version"], check=True, capture_output=True)
        print("✓ Docker and Docker Compose are available")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("✗ Docker or Docker Compose not found")
        print("Please install Docker and Docker Compose to run integration tests")
        return False


def start_test_database():
    """Start the test database container."""
    print("Starting test database...")

    # Check if container is already running
    result = run_command(
        ["docker", "ps", "--filter", "name=backend-postgres-test-1", "--format", "{{.Names}}"],
        check=False
    )

    if "backend-postgres-test-1" in result.stdout:
        print("✓ Test database container already running")
        return True

    # Start the container
    run_command(["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d"])

    # Wait for database to be ready
    print("Waiting for database to be ready...")
    max_retries = 30
    for i in range(max_retries):
        result = run_command(
            ["docker", "exec", "backend-postgres-test-1", "pg_isready", "-U", "postgres"],
            check=False
        )
        if result.returncode == 0:
            print("✓ Test database is ready")
            time.sleep(2)  # Give it a bit more time
            return True

        time.sleep(1)
        print(f"  Waiting... ({i+1}/{max_retries})")

    print("✗ Test database failed to start within timeout")
    return False


def stop_test_database():
    """Stop the test database container."""
    print("Stopping test database...")
    run_command(["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"], check=False)
    print("✓ Test database stopped")


def run_tests():
    """Run the integration tests."""
    print("Running integration tests...")

    # Run only integration tests
    cmd = [
        "python", "-m", "pytest",
        "tests/integration/",
        "-v",
        "--tb=short",
        "-x"  # Stop on first failure
    ]

    result = run_command(cmd, check=False)
    return result.returncode == 0


def main():
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
        # Start database
        if not start_test_database():
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
        # Always try to stop the database
        print("\n" + "=" * 50)
        stop_test_database()


if __name__ == "__main__":
    main()
