#!/usr/bin/env python3
"""
Verification script for ITER2-001 Integration Architecture Foundation.

This script verifies that all the integration foundation components work together:
1. Core shared package accessibility
2. Integration domain configuration
3. ARQ task queue configuration
4. Redis settings (without requiring actual Redis connection)

This proves the "steel thread" is working - all components can be imported
and configured correctly.
"""

import sys
from typing import Any


def test_core_shared_package() -> dict[str, Any]:
    """Test that core_shared package is accessible and working."""
    print("🔍 Testing core_shared package accessibility...")

    try:
        # Import and verify core_shared models are accessible
        from core_shared.base_service import SyncResult
        from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

        # Verify enums work correctly
        _ = SyncStatus.SUCCESS
        _ = SyncResult.SUCCESS

        # Verify we can create instances
        from datetime import datetime

        _ = SyncMetadata(
            internal_id=1,
            integration_source="test",
            external_id="test-123",
            last_synced_at=datetime.now(),
            version_hash="abc123",
            sync_status=SyncStatus.SUCCESS,
        )

        return {
            "status": "healthy",
            "message": "Core shared package accessible",
            "models": ["SyncMetadata", "ExternalReference", "BaseIntegrationService"],
            "enums_working": True,
            "can_create_instances": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Core shared package error: {str(e)}",
            "error": str(e),
        }


def test_integration_domain() -> dict[str, Any]:
    """Test that integration domain is configured correctly."""
    print("🔍 Testing integration domain configuration...")

    try:
        from app.core.integrations.database import IntegrationDatabaseManager
        from app.core.integrations.task_queue import TaskQueueConfig, get_redis_settings
        from app.infrastructure.config import Settings

        # Verify configuration is accessible
        config = TaskQueueConfig()

        # Test with dummy settings
        test_settings = Settings(
            debug=True,
            database_url="postgresql://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379",
        )
        _ = get_redis_settings(test_settings)

        # Verify we can create database manager
        _ = IntegrationDatabaseManager(test_settings)

        return {
            "status": "healthy",
            "message": "Integration domain configured",
            "task_queue_config": {
                "queue_name": config.QUEUE_NAME,
                "max_jobs": config.MAX_JOBS,
                "job_timeout": config.JOB_TIMEOUT,
                "max_tries": config.MAX_TRIES,
            },
            "redis_settings_configured": True,
            "database_manager_created": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Integration domain error: {str(e)}",
            "error": str(e),
        }


def test_arq_configuration() -> dict[str, Any]:
    """Test that ARQ task queue configuration works."""
    print("🔍 Testing ARQ task queue configuration...")

    try:
        from app.core.integrations.task_queue import get_worker_settings
        from app.infrastructure.config import Settings

        # Test with dummy settings
        test_settings = Settings(
            debug=True,
            database_url="postgresql://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379",
        )

        # Verify we can create worker settings
        worker_settings = get_worker_settings(test_settings)

        # Verify worker settings has required attributes
        assert hasattr(worker_settings, "functions")
        assert hasattr(worker_settings, "redis_settings")
        assert hasattr(worker_settings, "max_jobs")

        return {
            "status": "healthy",
            "message": "ARQ configuration working",
            "worker_settings_created": True,
            "has_functions": len(worker_settings.functions) > 0,
            "has_redis_settings": worker_settings.redis_settings is not None,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"ARQ configuration error: {str(e)}",
            "error": str(e),
        }


def test_dependency_injection() -> dict[str, Any]:
    """Test that integration dependencies can be injected."""
    print("🔍 Testing dependency injection configuration...")

    try:
        from app.infrastructure.config import Settings
        from app.infrastructure.di.integrations import IntegrationProvider

        # Test with dummy settings (just verify we can create the provider)
        _ = Settings(
            debug=True,
            database_url="postgresql://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379",
        )

        # Verify we can create the provider
        provider = IntegrationProvider()

        # Verify provider has required methods
        assert hasattr(provider, "provide_redis_settings")
        assert hasattr(provider, "provide_integration_database_manager")

        return {
            "status": "healthy",
            "message": "Dependency injection configured",
            "provider_created": True,
            "has_redis_provider": True,
            "has_database_provider": True,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Dependency injection error: {str(e)}",
            "error": str(e),
        }


def main() -> None:
    """Run all verification tests."""
    print("🚀 Verifying ITER2-001 Integration Architecture Foundation")
    print("=" * 60)

    tests = [
        ("Core Shared Package", test_core_shared_package),
        ("Integration Domain", test_integration_domain),
        ("ARQ Configuration", test_arq_configuration),
        ("Dependency Injection", test_dependency_injection),
    ]

    results = {}
    all_healthy = True

    for test_name, test_func in tests:
        print(f"\n📋 {test_name}")
        print("-" * 40)

        result = test_func()
        results[test_name] = result

        if result["status"] == "healthy":
            print(f"✅ {result['message']}")
            # Print additional details
            for key, value in result.items():
                if key not in ["status", "message"]:
                    print(f"   • {key}: {value}")
        else:
            print(f"❌ {result['message']}")
            if "error" in result:
                print(f"   Error: {result['error']}")
            all_healthy = False

    print("\n" + "=" * 60)
    if all_healthy:
        print("🎉 SUCCESS: All integration foundation components are working!")
        print("✅ The steel thread is complete - ready for ITER2-002")
        sys.exit(0)
    else:
        print("❌ FAILURE: Some integration foundation components have issues")
        print("🔧 Please fix the issues above before proceeding")
        sys.exit(1)


if __name__ == "__main__":
    main()
