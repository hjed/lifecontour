# Code Quality Standards

This document defines the consolidated code quality standards used across all development tools in this project.

## Overview

All linting and code quality tools in this project run the **same standardized checks** using **consistent virtual environment management** to ensure compatibility across:

- ✅ CI Pipeline (`.github/workflows/ci.yml`)
- ✅ Local Development Script (`./scripts/dev.sh lint`)
- ✅ AI Guidelines (`AGENTS.md`)
- ✅ Pre-commit Hooks (`.pre-commit-config.yaml`), including gitleaks secret scanning

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

### Core Shared (Python)

```bash
cd core_shared
uv run ruff check .          # Linting (code style, imports, etc.)
uv run ruff format --check . # Formatting verification
uv run mypy .                # Type checking
```

### Integration Workers (Python)

Every worker (`integration_workers/{google,immich,strava,snipeit}`) shares one
tooling configuration defined at the repo root, so `ruff`, `mypy`, and `pytest`
behave identically across workers. Run the checks from the worker directory,
pointing `mypy`/`pytest` at the shared config files:

```bash
cd integration_workers/<worker>
uv run ruff check .                                          # inherits ../../ruff.toml (via [tool.ruff] extend)
uv run ruff format --check .
uv run mypy --config-file ../../mypy.ini .                   # shared strict mypy config
uv run pytest -c ../../pytest.ini --rootdir . tests/unit/    # shared pytest config
uv run pytest -c ../../pytest.ini --rootdir . tests/integration/
```

See [Shared Worker Tooling Configuration](#shared-worker-tooling-configuration)
for how this is wired.

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

### Secret Scanning (gitleaks)

gitleaks blocks new secrets in two places, both using the committed `.gitleaks.toml` and
`.gitleaksignore`:

- **Pre-commit:** the upstream `gitleaks` hook (`gitleaks git --pre-commit --redact --staged --verbose`)
  scans staged changes. pre-commit builds gitleaks itself, so no separate install is needed.
- **CI:** the `secret-scan` job scans the commits each event introduces; see
  [CI/CD Setup → Secret scanning](ci-cd-setup.md#secret-scanning-secret-scan).

The hook `rev` and `GITLEAKS_VERSION` in `ci.yml` pin the same version (the audited
v8.30.1). Change both together; `core_shared/tests/unit/test_secret_scan.py` fails if
they differ.

**Running the gitleaks tests locally.** The `gitleaks`-marked integration tests need the
binary on `PATH` (or in `GITLEAKS_BIN`):

```bash
v=8.30.1  # GITLEAKS_VERSION in ci.yml; check the archive against GITLEAKS_SHA256
curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v$v/gitleaks_${v}_linux_x64.tar.gz" \
  | tar -xz -C ~/.local/bin gitleaks
cd core_shared && uv run pytest -m gitleaks
```

**When gitleaks flags something:**

1. **A real credential:** don't allowlist it. Remove it, and if it was ever committed,
   revoke or rotate it at the provider first. History is not rewritten, so add the
   finding's `Fingerprint` (from a `--report-format json` report) to `.gitleaksignore`
   and record the rotation in
   [the credential audit](security/open-source-release-audit.md).
2. **A false positive or a dev/test placeholder:** add it to an `[[allowlists]]` entry in
   `.gitleaks.toml`:
   - always set `targetRules` (a global allowlist's `paths` skip the whole file in
     gitleaks 8.30, real keys included; a test enforces this);
   - pair a path with a value regex under `condition = "AND"`, so a real key added to the
     same file is still caught;
   - `regexes` match the extracted secret, not the whole line; anchor them.
3. Re-run `gitleaks git --redact` (or the hook) to confirm the finding is gone.

## Shared Worker Tooling Configuration

The four integration workers previously each repeated the same `ruff`, `mypy`,
`pytest`, and `coverage` configuration in their own `pyproject.toml`, which drifts
over time. That configuration is now **defined once at the repo root and inherited
by every worker**, so linting, type-checking, and test settings change in one place.

| Tool | Shared source (repo root) | How a worker consumes it |
| --- | --- | --- |
| ruff | `ruff.toml` | `[tool.ruff]` in the worker `pyproject.toml` sets `extend = "../../ruff.toml"` (ruff's native inheritance). |
| mypy | `mypy.ini` | Invoked with `mypy --config-file ../../mypy.ini .` — the flag is passed for **deterministic** resolution. (mypy would also find this file by searching parent directories, since the worker's `pyproject.toml` no longer has a `[tool.mypy]` table, but the explicit flag keeps resolution independent of CWD and any intervening config.) |
| pytest | `pytest.ini` | Invoked with `pytest -c ../../pytest.ini --rootdir . …` — `-c` selects the shared config; `--rootdir .` pins rootdir back to the worker so node IDs stay worker-relative. |

Notes:

- **`mypy.ini`** carries the strict flag set plus `explicit_package_bases = true`
  (which makes the worker's current directory an automatic package base — no
  per-worker `mypy_path` needed). It also holds the third-party `ignore_missing_imports`
  overrides (`google.*`, `googleapiclient.*`, `redis.*`); these are inert for workers
  that don't import those modules, so one shared file is safe.
- **Worker `pyproject.toml`** keeps only what is genuinely worker-specific: `[project]`
  dependencies, `[tool.uv.sources]`/`[tool.uv]`, `[dependency-groups]`, `[build-system]`,
  and a `[tool.ruff]` block (`extend` + `target-version`) with a small
  `[tool.ruff.lint.extend-per-file-ignores]` (ruff anchors per-file-ignore globs to the
  config file's directory, so the root patterns cannot reach the worker's `tests/`).
- **Dev tooling versions** — the `[dependency-groups] dev` set
  (`pytest`, `pytest-asyncio`, `ruff`, `mypy`) is intentionally kept identical in each
  worker: `uv` cannot share dependency groups across projects without a workspace, and a
  workspace would neither share `[tool.*]` config nor play well with the workers'
  standalone `uv pip install --no-sources .` Docker builds. This is the canonical dev set.
- **Coverage** config was removed from the workers — CI never runs `--cov` for a worker,
  so it was dead configuration (coverage.py does not read `pytest.ini`; add a root
  `.coveragerc` only if worker coverage is ever needed).

A governance test (`core_shared/tests/unit/test_worker_tooling_standardisation.py`) runs on
every PR and asserts the workers keep this shape (no inline `mypy`/`pytest`/`coverage`
config, `ruff` extends the shared file, `requires-python == ">=3.14"`, and the canonical
`Dockerfile` pattern), so the duplication cannot silently return.

## Python Language Rules

### Secrets must use `SecretStr`

All secret-bearing settings fields in the **integration workers** — for example
`database_url`, `encryption_key`, and any API client secret — **must** be typed
as `pydantic.SecretStr` rather than a bare `str`. This keeps secrets out of logs,
`repr()`/`str()` output, and tracebacks.

- Declare the field as `SecretStr` (the shared `core_shared.BaseWorkerSettings`
  already declares `database_url: SecretStr`).
- Read the raw value **only at the call site that needs it**, via
  `.get_secret_value()` (e.g. `create_session_factory(settings.database_url.get_secret_value())`).
- Do not log or interpolate the raw secret anywhere else.

The backend's own settings (`backend/app/infrastructure/config.py`) still type
several secrets as plain `str`; migrating them to `SecretStr` is not yet done.
New backend secret fields **should** prefer `SecretStr`, and existing ones should
be converted opportunistically, but the hard requirement above currently applies
to the integration workers only.

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

# This runs linting for:
# - Backend (backend/)
# - Core Shared (core_shared/)
# - Frontend (frontend/)

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
