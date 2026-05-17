import sys
import subprocess
import os

from tests.integration.conftest import get_async_database_url
env = os.environ.copy()
env["DATABASE_URL"] = get_async_database_url()
env["UV_NO_ENV"] = "1"

print("Downgrading to 0071...")
subprocess.run(["uv", "run", "alembic", "downgrade", "0071"], env=env, check=True)
print("Upgrading to head...")
subprocess.run(["uv", "run", "alembic", "upgrade", "head"], env=env, check=True)
