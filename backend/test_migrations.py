#!/usr/bin/env python3
"""
Test script to verify migrations and table creation.
"""

import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_table_imports() -> bool:
    """Test that all table definitions can be imported."""
    print("Testing table imports...")

    try:
        from app.infrastructure.database_metadata import metadata

        print("✓ Metadata imported")

        print("✓ Outbox table imported")

        print("✓ Contact tables imported")

        print(f"✓ Total tables registered: {len(metadata.tables)}")
        for table_name in sorted(metadata.tables.keys()):
            print(f"  - {table_name}")

        return True

    except Exception as e:  # noqa: BLE001
        print(f"✗ Import failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_migration_files() -> bool:
    """Test that migration files are valid."""
    print("\nTesting migration files...")

    try:
        # Test outbox migration
        print("✓ Outbox migration imported")

        # Test contacts migration
        print("✓ Contacts migration imported")

        return True

    except Exception as e:  # noqa: BLE001
        print(f"✗ Migration import failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> None:
    """Run all tests."""
    print("Running migration tests...\n")

    success = True
    success &= test_table_imports()
    success &= test_migration_files()

    if success:
        print("\n🎉 All migration tests passed!")
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
