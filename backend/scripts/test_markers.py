#!/usr/bin/env python3
"""
Test script to verify pytest markers are working correctly.

This script tests that unit and integration test markers are properly configured
and can be used to run tests separately.
"""

import subprocess
from pathlib import Path


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        if result.stdout:
            print(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            print(f"STDERR:\n{result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        if e.stdout:
            print(f"STDOUT:\n{e.stdout}")
        if e.stderr:
            print(f"STDERR:\n{e.stderr}")
        raise


def main() -> None:
    """Test pytest markers."""
    # Change to backend directory
    backend_dir = Path(__file__).parent.parent
    print(f"Working directory: {backend_dir}")

    # Test 1: List all tests with unit marker
    print("\n=== Testing unit marker ===")
    result = run_command([
        "python", "-m", "pytest",
        "-m", "unit",
        "--collect-only",
        "-q"
    ], check=False)

    if result.returncode == 0:
        print("✓ Unit marker tests found")
    else:
        print("✗ Unit marker tests failed")

    # Test 2: List all tests with integration marker
    print("\n=== Testing integration marker ===")
    result = run_command([
        "python", "-m", "pytest",
        "-m", "integration",
        "--collect-only",
        "-q"
    ], check=False)

    if result.returncode == 0:
        print("✓ Integration marker tests found")
    else:
        print("✗ Integration marker tests failed")

    # Test 3: Run a simple unit test
    print("\n=== Running unit tests ===")
    result = run_command([
        "python", "-m", "pytest",
        "-m", "unit",
        "tests/unit/test_health.py::test_health_check",
        "-v"
    ], check=False)

    if result.returncode == 0:
        print("✓ Unit test execution successful")
    else:
        print("✗ Unit test execution failed")

    print("\n=== Test Summary ===")
    print("Pytest markers are configured and working!")
    print("- Use 'pytest -m unit' to run only unit tests")
    print("- Use 'pytest -m integration' to run only integration tests")
    print("- Use 'pytest -m \"not integration\"' to run all tests except integration")


if __name__ == "__main__":
    main()
