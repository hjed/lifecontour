# CI/CD Setup Documentation

This document describes the Continuous Integration and Continuous Deployment (CI/CD) setup for Lifecontour.

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
  - Both run only when the `frontend_checks` path filter (`frontend/**`) matches, and
    always on pushes and release runs. The E2E jobs keep their own triggers (backend,
    `core_shared`, frontend source and E2E infrastructure changes), so a backend-only PR
    still runs E2E with `frontend-lint` skipped. Only a *failed* `frontend-lint` holds
    E2E back
- `build-test`: Tests Docker builds for both components
- `secret-scan`: Runs gitleaks over the commits the event introduces; fails on any new
  finding. See [Secret scanning](#secret-scanning-secret-scan)
- `frontend-image`: Builds the production frontend image (the Dockerfile's `runner`
  stage) and runs `docker/frontend/verify-image.sh` against it. The script checks that the
  image has no `.next/cache`, dev dependencies or pnpm store, that it refuses to start
  without `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY`, and that it serves pages, static assets
  and the third-party notices. The e2e suite serves the frontend from source, so this is
  the only CI check of the published image. It runs when the `frontend_image` path filter
  matches (`docker/frontend/**`, `next.config.mjs`, the package and lock files,
  `frontend/public/**`, the notices script), and on every release run. See
  [Deployment Guide → Frontend Image](architecture/deployment-guide.md#frontend-image)

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
  jobs must keep that dependency. A job whose `if` uses a status function (`!cancelled()`,
  `always()`) no longer skips with its dependencies, so it must also require
  `needs.changes.result == 'success'` (or success of a job that needs `changes`), as the
  E2E jobs do.
- Run CI on an upper layer by hand with `gh workflow run ci.yml --ref <branch>`. The
  path filter diffs against the merge-base with `main`, so the run covers the layers below.
  Re-running the skipped PR run does not work: it replays the same event.
- When the PR below merges, the retarget fires no CI event; the new bottom layer runs
  on its next push, or dispatch it manually.
- **No stack layer merges without a passing `secret-scan` run on its head**, either as
  the bottom layer or through `gh workflow run ci.yml --ref <branch>`. A dispatched run
  scans the branch's full history, so it covers every layer below it too. The pre-commit
  hook (and GitHub push protection once the repository is public) are backstops that do
  not depend on CI.
- Fork PRs are never upper layers: a PR's base must be an upstream branch, so every fork PR
  targets `main` and runs the full in-gate CI, `secret-scan` included, once its first-run
  workflow approval is given. External contributors submit dependent changes as sequential
  PRs against `main`; to stack them, the maintainer pushes the layers to upstream branches.

#### Secret scanning (`secret-scan`)

The job installs the gitleaks CLI at the version pinned in `ci.yml` (`GITLEAKS_VERSION`,
verified against `GITLEAKS_SHA256`) and runs `scripts/secret_scan.py` over a
`fetch-depth: 0` checkout. The script picks the commit range from the event and runs
`gitleaks git --redact` with the committed `.gitleaks.toml` and `.gitleaksignore`:

| Event | Range scanned |
| --- | --- |
| `pull_request` | `base.sha..head.sha` |
| `push` | `before..after`; the full history of `after` when `before` is the zero SHA (new branch or tag) or no longer exists (force-push) |
| `workflow_dispatch`, `workflow_call` (release tags), anything else | the full history of `HEAD` |

- It has no path filter and `needs: changes`, so it runs on every in-gate event and
  skips on upper stack layers like every other job.
- Before scanning, it runs the `gitleaks`-marked integration tests
  (`core_shared/tests/integration/test_secret_scan_gitleaks.py`), which prove the committed
  config still catches a fake AWS key, including in allowlisted files.
- Output is redacted because Actions logs are public: a finding shows its rule, file,
  line and commit, never the value.
- It uses the CLI rather than `gitleaks-action`, so it needs no `GITHUB_TOKEN` or other
  secret.
- The pre-commit hook pins the same version; a unit test
  (`core_shared/tests/unit/test_secret_scan.py`) fails if the two drift.
- A finding is fixed by removing the secret (and rotating it if it was real), or, for a
  false positive, by allowlisting it; see
  [Code Quality Standards → Secret Scanning](code-quality-standards.md#secret-scanning-gitleaks).

#### Workflow security rules

- **Never use `pull_request_target` with a checkout of PR code.** It runs with the base
  repository's secrets and a write token, so checking out and running a fork's code in it
  hands that code the secrets.
- Workflows that run on PRs reference no repository secrets, so fork PRs run CI unchanged.
  The only secret in any workflow is `GITHUB_TOKEN` in `release.yml`, which runs on tags.

### 2. Security Scanning (`.github/workflows/security.yml`)

**Triggers:** Push/PR to main branches + weekly schedule

**Jobs:**
- `backend-security`: Safety and Bandit security scans
- `frontend-security`: npm audit and ESLint security rules
- `codeql-analysis`: GitHub's CodeQL analysis
- `docker-security`: Trivy vulnerability scanning

Secret scanning is not part of this workflow: it runs on every commit through the gitleaks
pre-commit hook and the `secret-scan` job in `ci.yml` (see
[Secret scanning](#secret-scanning-secret-scan)), using the committed `.gitleaks.toml`
(allowlist) and `.gitleaksignore` (fingerprints of rotated credentials). The pre-release
credential audit, including how to re-run it, is recorded in
[Open-Source Release Credential Audit](./security/open-source-release-audit.md).

### 3. Release Workflow (`.github/workflows/release.yml`)

**Triggers:** Git tags (`v*.*.*`) + manual dispatch

**Jobs:**
- `test`: Runs full CI suite
- `build-and-push-images`: Builds and pushes Docker images
- `create-release`: Creates GitHub release with changelog

**Images:** `build-and-push-images` publishes one image per service to
`ghcr.io/<github.repository>-<service>` (`backend`, `frontend`, `google-worker`,
`strava-worker`, `snipeit-worker`, `immich-worker`), plus the shared `python-base` image they
build on. Each is tagged with the release version. Today
that is `ghcr.io/hjed/lifecontour-*`, e.g. `ghcr.io/hjed/lifecontour-backend:v1.2.3`.

- The path follows `github.repository` (`IMAGE_NAME` in `release.yml`), so renaming the
  repository renames the images. It is deliberately not pinned
  ([spec](./product-specifications/open-source-release-and-branding-product-specification.md#decision-images-follow-the-repository-name)).
- After a rename, update the production deployment's image references at the next release.
  Packages published under the old name stay pullable, which keeps rollback possible.
- The frontend image needs `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` set in the deployment, or
  it will not start. See
  [Deployment Guide → Frontend Image](architecture/deployment-guide.md#frontend-image).

## Configuration Files

### Dependabot (`.github/dependabot.yml`)
- Automated dependency updates for Python, npm, GitHub Actions, and Docker
- Weekly schedule with PR limits
- Ignores major version updates for critical packages

### SonarCloud
- Code quality and security analysis, with a quality gate on every PR
- Runs as SonarCloud **Automatic Analysis** (the GitHub App), not an Actions step, so there is
  no workflow or token for it in this repository
- Automatic Analysis reads only `.sonarcloud.properties`, which this repository does not have,
  so the project's settings live in the SonarCloud UI. The scanner-CLI file
  `sonar-project.properties` was never read and has been removed.

### Issue Templates
- Bug report template with environment details
- Feature proposal template: the "discuss first" issue that precedes a pull request
  ([CONTRIBUTING](../CONTRIBUTING.md))
- `config.yml` disables blank issues and sends security reports to `SECURITY.md`

### Pull Request Template
- Linked issue, diff size (≤500 lines) and tests run
- AI-assistance disclosure and CLA acknowledgement
- Maintainer check that `secret-scan` passed on the head ([Stacked PRs](#stacked-prs))

## Public Repository Settings

The repository is public. These settings live in GitHub, not in the tree, so this section is
their record. Re-check them with the `gh api` reads listed under each one.

### CLA Assistant

- The hosted [CLA Assistant](https://cla-assistant.io) is linked to the repository, with
  [`CLA.md`](../CLA.md) published as its gist. It comments on each PR whose author has not
  signed, and posts the `license/cla` commit status. See
  [CONTRIBUTING](../CONTRIBUTING.md) for the contributor side.
- **Bots are allowlisted** in its settings (`dependabot[bot]`, `github-actions[bot]`,
  `Copilot`), so the required `license/cla` check does not block them.
- CLA Assistant was linked just after the flip, because it needs the repository to be public.
  `license/cla` became a required check only after it was live, so open PRs were not left
  waiting on a status that would never arrive.
- CLA Assistant only reports on PR events. When the CLA or its allowlist changes, use the
  "recheck" link in its comment (or push to the PR) to refresh an open PR's status.

### Ruleset on `main`

A branch ruleset (`gh api repos/hjed/lifecontour/rulesets`) on the default branch:

- **Pull request required**, with 0 required approvals. There is one maintainer, who cannot
  approve their own PRs, so requiring a PR is what blocks direct pushes.
- **No force-push, no deletion** of `main`.
- **Bypass:** the repository admin role, in `pull_request` mode only. An emergency PR can be
  merged past a failing check; nobody can push to `main` directly.
- **Required status checks** (not strict, so a branch need not be up to date with `main`; with
  bottom-only stack CI that would force constant re-runs):
  - `license/cla` (a commit status from CLA Assistant);
  - from GitHub Actions: Backend Linting, Core Shared Linting, Backend Unit Tests, Core Shared
    Unit Tests, Backend Integration Tests, Frontend Linting, Frontend Tests, E2E Docker Image
    Build, Frontend Image Check, and Secret Scan (gitleaks).
- **Matrix jobs are not required** (Worker Lint, Unit and Integration Tests; Frontend E2E
  Tests). When a matrix job is skipped by a path filter or the stack gate, its check is
  reported under the literal `${{ matrix.* }}` name, so a required `Frontend E2E Tests
  (firefox)` would never arrive on a docs-only PR. A failing matrix job is still visible on the
  PR and must not be merged past.
- Every required job has `needs: changes` and always reports, run or skipped, and GitHub
  treats a skipped check as passing. That is what lets path-filtered PRs and upper stack
  layers through.
- **Known gap:** an upper stack layer reports every check as skipped. If it is retargeted to
  `main` without a new head commit, nothing re-runs and the ruleset passes it with no CI. The
  [Stacked PRs](#stacked-prs) rule still applies: no layer merges without a passing
  `secret-scan` on its head, checked by the maintainer (it is on the PR template). Do not close
  this gap by loosening the stack gate.
- The disabled `copilot` ruleset is unrelated (Copilot code review) and is not a protection.

### Fork PRs and workflow approval

- **First-time contributors need approval** before their workflows run
  (`actions/permissions/fork-pr-contributor-approval`, policy `first_time_contributors`).
  Read the diff before approving: approval runs the fork's code on GitHub's runners.
- Fork PRs get a read-only `GITHUB_TOKEN` and no secrets. CI needs neither, so it runs
  unchanged ([Workflow security rules](#workflow-security-rules)). Fork PRs always target
  `main`, so they always run the full in-gate CI.
- The Actions caches were purged just before the flip, because fork-PR runs can restore
  base-branch caches that predate the credential audit. Caches created since are public-era.

### Security features

- **Secret scanning and push protection** are on. Push protection rejects a push containing
  a recognised credential, as a backstop to the gitleaks hook and `secret-scan` job. Alerts
  are triaged as in the [credential audit](./security/open-source-release-audit.md).
- **Private vulnerability reporting** is on; [`SECURITY.md`](../SECURITY.md) sends reporters
  to it.
- **Dependabot alerts** and automated security fixes are on, alongside the version updates in
  `.github/dependabot.yml`.

### Container packages

- The `ghcr.io/hjed/lifecontour-*` packages are **public**, so self-hosters can
  `docker pull` without logging in. Every package is linked to this repository through the
  image's `org.opencontainers.image.source` label.
- The legacy `ghcr.io/hjed/personal-management-system-*` packages stay **private**. They are
  kept only for rollback, and their frontend versions predate the
  [frontend image hardening](architecture/deployment-guide.md#frontend-image).
- Making a package public cannot be undone.

## Setup Instructions

### 1. Repository Secrets

None. No workflow that runs on a PR references a repository secret
([Workflow security rules](#workflow-security-rules)), and `release.yml` uses only the
built-in `GITHUB_TOKEN`.

### 2. External Service Setup

**Codecov:**
1. Sign up at https://codecov.io and add the repository
2. Uploads are tokenless: the `codecov/codecov-action` steps pass no token, which Codecov
   accepts for a public repository. An upload failure does not fail CI.

**SonarCloud:**
1. Sign up at https://sonarcloud.io
2. Import your repository
3. Keep Automatic Analysis enabled; no token or properties file is needed

### 3. Dependabot Configuration

`.github/dependabot.yml` is ready to use; adjust the schedules and groups there.

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