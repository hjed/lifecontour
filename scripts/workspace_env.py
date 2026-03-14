#!/usr/bin/env python3
import hashlib
import json
import os
import sys
from pathlib import Path

def get_workspace_env():
    # Use the absolute path of the workspace (root of the repo)
    workspace = str(Path(__file__).parent.parent.absolute())

    is_ci_val = os.environ.get("CI", "").lower()
    is_github_actions_val = os.environ.get("GITHUB_ACTIONS", "").lower()
    is_ci = is_ci_val in ("true", "1", "yes") or is_github_actions_val in ("true", "1", "yes")

    if is_ci:
        offset = 0
    else:
        # Modulo 99 + 1 gives 1-99 to avoid falling back to plain 'pms' prefix for local dev workspaces
        offset = (int(hashlib.sha1(workspace.encode()).hexdigest(), 16) % 99) + 1

    # Base ports for testing
    prefix = f"pms_test_{offset}" if offset > 0 else "pms"

    # Multiply offset by 10 to space out port blocks comfortably
    port_offset = offset * 10

    env = {
        "CONTAINER_PREFIX": prefix,
        "COMPOSE_PROJECT_NAME": prefix,
        "FRONTEND_TEST_PORT": str(3100 + port_offset),
        "BACKEND_TEST_PORT": str(8001 + port_offset),
        "DB_TEST_PORT": str(5433 + port_offset),
        "MEILI_TEST_PORT": str(7701 + port_offset),
        "REDIS_TEST_PORT": str(6380 + port_offset),
        "OAUTH_PUBLIC_TEST_PORT": str(4446 + port_offset),
        "OAUTH_ADMIN_TEST_PORT": str(4447 + port_offset),
        "OAUTH_UI_TEST_PORT": str(3002 + port_offset),
        "DB_PORT": str(5433 + port_offset),
        "MEILI_PORT": str(7701 + port_offset),
        "REDIS_PORT": str(6380 + port_offset),
        "BACKEND_PORT": str(8001 + port_offset),
        "FRONTEND_PORT": str(3100 + port_offset),
        "OAUTH_PUBLIC_PORT": str(4446 + port_offset),
        "OAUTH_ADMIN_PORT": str(4447 + port_offset),
        "OAUTH_UI_PORT": str(3002 + port_offset),
    }
    return env

def main():
    env = get_workspace_env()

    output_format = sys.argv[1] if len(sys.argv) > 1 else "json"

    if output_format == "json":
        print(json.dumps(env, indent=2))
    elif output_format == "export":
        for k, v in env.items():
            print(f"export {k}={v}")
    elif output_format == "ps1":
        for k, v in env.items():
            print(f"$env:{k}='{v}'")
    elif output_format in env:
        print(env[output_format])
    else:
        print(f"Unknown format or key: {output_format}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
