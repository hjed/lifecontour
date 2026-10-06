# Pre-commit Hooks Setup

This document describes the pre-commit hooks configuration for the Lifecontour project.

## Overview

Pre-commit hooks automatically run code quality checks before each commit, ensuring consistent code style and catching issues early. The hooks are configured to run:

### Backend (Python)
- **ruff format**: Code formatting using ruff (replaces black)
- **ruff check**: Linting with automatic fixes
- **mypy**: Type checking

### Frontend (TypeScript/React)
- **prettier**: Code formatting
- **eslint**: Linting with automatic fixes
- **tsc --noEmit**: TypeScript type checking

### General
- **trailing-whitespace**: Remove trailing whitespace
- **end-of-file-fixer**: Ensure files end with newline
- **check-yaml**: Validate YAML files
- **check-json**: Validate JSON files
- **check-toml**: Validate TOML files
- **check-merge-conflict**: Check for merge conflict markers
- **check-added-large-files**: Prevent large files from being committed

## Installation

Pre-commit hooks are automatically installed when you run:

```bash
./scripts/dev.sh setup
```

## Manual Usage

You can run pre-commit hooks manually:

```bash
# Run all hooks on all files
./scripts/dev.sh precommit

# Run specific hook
backend/.venv/bin/pre-commit run ruff-format --all-files

# Run hooks on specific files
backend/.venv/bin/pre-commit run --files backend/app/main.py
```

## Configuration

The pre-commit configuration is defined in `.pre-commit-config.yaml` at the project root.

### Backend Configuration Changes

- **Switched from black to ruff format**: Ruff now handles both linting and formatting
- **Updated pyproject.toml**: Added ruff format configuration, removed black dependency
- **Updated dev scripts**: Modified `scripts/dev.sh` to use `ruff format` instead of `black`

## Troubleshooting

### Hook Failures

If a hook fails:

1. **Formatting issues**: The hook will automatically fix most issues. Just add the changes and commit again.
2. **Linting errors**: Review the output and fix the issues manually.
3. **Type checking errors**: Fix type annotations or add appropriate ignores.

### Skipping Hooks

In rare cases, you can skip hooks (not recommended):

```bash
git commit --no-verify -m "commit message"
```

### Updating Hooks

To update hook versions:

```bash
backend/.venv/bin/pre-commit autoupdate
```

## Integration with Development Workflow

The pre-commit hooks integrate with the existing development workflow:

- **Development script**: `./scripts/dev.sh lint` and `./scripts/dev.sh lint-fix` use the same tools
- **CI/CD**: The same tools should be used in continuous integration
- **IDE integration**: Configure your IDE to use the same tools (ruff, eslint, prettier, mypy)

## Benefits

- **Consistent code style**: Automatic formatting ensures consistent style across the codebase
- **Early error detection**: Catch linting and type errors before they reach the repository
- **Reduced review time**: Less time spent on style discussions in code reviews
- **Automated fixes**: Many issues are automatically fixed without manual intervention
