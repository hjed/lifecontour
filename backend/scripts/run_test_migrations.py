#!/usr/bin/env python3
"""Script to run database migrations for test environment."""

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

# Add the app directory to the Python path
backend_dir = Path(__file__).parent.parent
app_dir = backend_dir / "app"
sys.path.insert(0, str(app_dir))


def run_migrations() -> None:
    """Run Alembic migrations for test database."""
    try:
        # Set test environment
        os.environ["ENVIRONMENT"] = "test"

        # Configure Alembic
        alembic_cfg = Config(str(backend_dir / "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", str(backend_dir / "app" / "migrations")
        )

        # Run migrations
        print("Running database migrations for test environment...")
        command.upgrade(alembic_cfg, "head")
        print("Migrations completed successfully")

    except Exception as e:
        print(f"Error running migrations: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_migrations()
