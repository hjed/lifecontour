# Code Quality Standards

This document defines the consolidated code quality standards used across all development tools in this project.

## Overview

All linting and code quality tools in this project run the **same standardized checks** using **consistent virtual environment management** to ensure compatibility across:

- ✅ CI Pipeline (`.github/workflows/ci.yml`)
- ✅ Local Development Script (`./scripts/dev.sh lint`)
- ✅ AI Guidelines (`docs/ai-guidelines.md`)
- ✅ Pre-commit Hooks (`.pre-commit-config.yaml`)

## Virtual Environment Standardization

All Python tools use **UV with virtual environments** for consistency:

- **CI**: Uses `uv venv` + `uv run <command>`
- **Local Dev**: Uses `uv venv` + `uv run <command>`
- **Pre-commit**: Uses local virtual environment at `backend/.venv/`
- **AI Guidelines**: Documents `uv run <command>` usage

## Standardized Quality Checks

### Backend (Python)

```bash
cd backend
uv run ruff check .          # Linting (code style, imports, etc.)
uv run ruff format --check . # Formatting verification
uv run mypy .                # Type checking
```

### Frontend (TypeScript/React)

```bash
cd frontend
pnpm lint             # ESLint (Next.js config)
pnpm type-check       # TypeScript compiler check
pnpm format:check     # Prettier formatting verification
```

### General File Checks

- Remove trailing whitespace
- Ensure files end with newline
- Validate YAML/JSON/TOML syntax
- Check for merge conflict markers
- Prevent large files (>1MB) from being committed

## Tool-Specific Behavior

### Pre-commit Hooks (Auto-fix)
Pre-commit hooks **automatically fix** issues before commit:
- `uv run ruff format` (not `--check`)
- `pnpm format` (not `format:check`)
- `pnpm lint:fix` (not just `lint`)

### CI/Dev Scripts/AI Guidelines (Verification)
These tools **verify** that code is properly formatted and fail if issues exist:
- `uv run ruff format --check`
- `pnpm format:check`
- `pnpm lint` (without `--fix`)

## Usage Commands

### Local Development
```bash
# Check all quality standards (same as CI)
./scripts/dev.sh lint

# Auto-fix issues
./scripts/dev.sh lint-fix

# Run pre-commit hooks manually
./scripts/dev.sh precommit
```

### Individual Tools
```bash
# Backend only
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy .

# Frontend only
cd frontend && pnpm lint && pnpm type-check && pnpm format:check
```

## Virtual Environment Setup

### Initial Setup
```bash
# Run once to set up the development environment
./scripts/dev.sh setup
```

This creates:
- `backend/.venv/` - Python virtual environment with all dependencies
- `frontend/node_modules/` - Node.js dependencies via pnpm

### Manual Setup (if needed)
```bash
# Backend virtual environment
cd backend
uv venv
uv pip install -e .[dev]

# Frontend dependencies
cd frontend
pnpm install
```

## Integration with Development Workflow

1. **Setup script** creates virtual environments consistently
2. **Pre-commit hooks** auto-fix issues when you commit
3. **Local dev script** verifies everything is clean using same commands as CI
4. **CI pipeline** blocks merges if standards aren't met
5. **AI guidelines** document the same requirements for AI assistants

This ensures that code quality is maintained consistently across all development environments and workflows, with no surprises between local development and CI.
