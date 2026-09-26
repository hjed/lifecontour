# CI/CD Setup Documentation

This document describes the Continuous Integration and Continuous Deployment (CI/CD) setup for the Personal Management System.

## Overview

The CI/CD pipeline is implemented using GitHub Actions and includes:

- **Automated testing** for both backend (Python/FastAPI) and frontend (Next.js/TypeScript)
- **Code quality checks** including linting, formatting, and type checking
- **Security scanning** for vulnerabilities and code analysis
- **Automated dependency updates** via Dependabot
- **Release automation** with Docker image building and publishing

## Workflows

### 1. Main CI Workflow (`.github/workflows/ci.yml`)

**Triggers:** Push and PR to `main`/`develop` branches; manual `workflow_dispatch`
(`gh workflow run ci.yml --ref <branch>`); `workflow_call` from the release workflow

**Jobs:**
- `backend-lint`: Runs Ruff, Black, and MyPy on Python code
- `backend-test`: Runs pytest with PostgreSQL service
- `core-shared-unit-test`: Runs the `core_shared` unit suite (includes the worker
  tooling-standardisation governance test); runs on every PR
- `worker-lint`: Per-worker matrix — `ruff check`, `ruff format --check`, and
  `mypy --config-file ../../mypy.ini .` against the shared tooling config
- `worker-unit-test` / `worker-integration-test`: Per-worker matrix running
  `pytest -c ../../pytest.ini --rootdir . tests/unit|integration/`
- `frontend-lint`: Runs ESLint, TypeScript check, and Prettier
- `frontend-test`: Runs Jest tests with coverage
- `build-test`: Tests Docker builds for both components

**Features:**
- Parallel execution for faster feedback
- Dependency caching for improved performance
- Coverage reporting to Codecov
- PostgreSQL service for integration tests
- **Shared worker tooling:** worker `ruff`/`mypy`/`pytest` config lives once at the repo
  root (`ruff.toml`, `mypy.ini`, `pytest.ini`) and every worker inherits it, so the
  quality gates behave identically across workers. The worker `paths-filter` blocks include
  these shared files so a change to them re-runs the dependent worker jobs. See
  [Code Quality Standards → Shared Worker Tooling Configuration](code-quality-standards.md#shared-worker-tooling-configuration).
- **Canonical worker Dockerfile:** all workers build from the same template
  (`FROM pms-python-base`, copy `pyproject.toml` then source, `uv pip install --system
  --no-cache-dir --no-sources .`, Redis-ping `HEALTHCHECK` via `os.environ['REDIS_URL']`,
  `USER appuser`, `CMD ["python", "worker.py"]`). See
  [Integration Architecture → Canonical Worker Dockerfile](architecture/integration-architecture.md#canonical-worker-dockerfile).

#### Stacked PRs

Only the **lowest unmerged** PR of a native PR stack runs CI; upper layers skip every
job. This is deliberate to save Actions budget — do not remove it.

- GitHub runs `pull_request` workflows for every PR in a stack as if it targeted the
  stack's base (`main`), so the `branches: [main, develop]` filter alone matches every layer.
- The `changes` job is gated on `github.event.pull_request.stack == null ||
  github.event.pull_request.stack.base.ref == github.event.pull_request.base.ref`
  (see GitHub's [Optimizing CI for stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/optimizing-ci-for-stacked-pull-requests)).
  Every other job depends on `changes`, directly or transitively, so it skips too. New
  jobs must keep that dependency.
- Run CI on an upper layer by hand with `gh workflow run ci.yml --ref <branch>`. The
  path filter diffs against the merge-base with `main`, so the run covers the layers below.
  Re-running the skipped PR run does not work: it replays the same event.
- When the PR below merges, the retarget fires no CI event; the new bottom layer runs
  on its next push, or dispatch it manually.

### 2. Security Scanning (`.github/workflows/security.yml`)

**Triggers:** Push/PR to main branches + weekly schedule

**Jobs:**
- `backend-security`: Safety and Bandit security scans
- `frontend-security`: npm audit and ESLint security rules
- `codeql-analysis`: GitHub's CodeQL analysis
- `docker-security`: Trivy vulnerability scanning

### 4. Dependency Updates (`.github/workflows/dependency-update.yml`)

**Triggers:** Weekly schedule (Mondays) + manual dispatch

**Jobs:**
- `update-backend-dependencies`: UV-based Python updates
- `update-frontend-dependencies`: pnpm-based Node.js updates

### 5. Release Workflow (`.github/workflows/release.yml`)

**Triggers:** Git tags (`v*.*.*`) + manual dispatch

**Jobs:**
- `test`: Runs full CI suite
- `build-and-push-images`: Builds and pushes Docker images
- `create-release`: Creates GitHub release with changelog

## Configuration Files

### Dependabot (`.github/dependabot.yml`)
- Automated dependency updates for Python, npm, GitHub Actions, and Docker
- Weekly schedule with PR limits
- Ignores major version updates for critical packages

### SonarCloud (`sonar-project.properties`)
- Code quality and security analysis
- Coverage integration
- Quality gate enforcement

### Issue Templates
- Bug report template with environment details
- Feature request template with acceptance criteria

### Pull Request Template
- Comprehensive checklist for code quality
- Testing requirements
- Documentation updates

## Setup Instructions

### 1. Repository Secrets

Add these secrets to your GitHub repository:

```
SONAR_TOKEN          # SonarCloud authentication token
CODECOV_TOKEN        # Codecov token (for private repos)
```

### 2. External Service Setup

**Codecov:**
1. Sign up at https://codecov.io
2. Add your repository
3. Configure token (if private repo)

**SonarCloud:**
1. Sign up at https://sonarcloud.io
2. Import your repository
3. Generate and add SONAR_TOKEN
4. Update `sonar-project.properties` with your organization

### 3. Dependabot Configuration

Update `.github/dependabot.yml`:
- Replace `YOUR_USERNAME` with your GitHub username
- Adjust reviewers and assignees as needed

### 4. Badge Integration

Add status badges to your README.md (see `.github/README-badges.md`)

## Local Development Integration

The CI/CD setup integrates with local development and Docker Compose:

```bash
# Run the same checks locally
./scripts/dev.sh lint      # Same as CI linting
./scripts/dev.sh test      # Same as CI testing
./scripts/dev.sh lint-fix  # Fix linting issues

# Run tests with Docker Compose
docker compose --profile test --env-file .env.test up
cd frontend && pnpm test:e2e
cd backend && pytest tests/integration/
docker compose --profile test down -v
```

For detailed Docker Compose setup, see [Docker Compose Unified Setup](./DOCKER_COMPOSE_UNIFIED.md).

## Coverage Requirements

### Backend (Python)
- Minimum 70% coverage (configured in `pyproject.toml`)
- Excludes test files, migrations, and `__init__.py`

### Frontend (TypeScript)
- Minimum 70% coverage (configured in `jest.config.js`)
- Excludes type definitions and story files

## Quality Gates

### Code Quality Checks
- All linting must pass (Ruff, ESLint)
- All formatting must be correct (Black, Prettier)
- All type checking must pass (MyPy, TypeScript)
- All tests must pass
- Coverage thresholds must be met

### Security Checks
- No high-severity vulnerabilities
- Security linting passes
- Docker images pass vulnerability scans

### Documentation
- Code changes should include documentation updates
- Complex logic should be commented
- API changes must be documented

## Troubleshooting

### Common Issues

1. **Test failures in CI but not locally**
   - Check environment variables
   - Verify database service configuration
   - Check for timing issues in async tests

2. **Linting failures**
   - Run `./scripts/dev.sh lint-fix` locally
   - Ensure all files are committed

3. **Coverage failures**
   - Add tests for uncovered code
   - Update coverage exclusions if needed

4. **Docker build failures**
   - Test builds locally with same Dockerfile
   - Check for missing dependencies

### Performance Optimization

- Dependency caching reduces build times by ~50%
- Parallel job execution provides faster feedback
- Matrix builds for multiple environments when needed
