# Open-Source Release Credential Audit

The pre-release credential audit required by the
[Open-Source Release & Branding spec, Part 3](../product-specifications/open-source-release-and-branding-product-specification.md#part-3-security-audit--guardrails)
and delivered by [ITER19-001](../tasks/iteration-19-open-source-release-and-branding.md#iter19-001-credential-audit--secret-scanning-guardrails).
It is the **release gate** for the visibility flip (ITER19-005 Phase 2): the flip happens only
with zero unresolved real-credential findings.

**This record never contains a secret value.** Findings are identified by scanner, rule, file and
commit only.

| Part | Scope | Status |
|---|---|---|
| Phase 1 | Git history (every ref) and the current tree | ✅ Complete: 0 real credentials, gate met |
| Phase 3 | GitHub-side content (PR/issue text, Actions logs and artifacts, releases, GHCR layers) | Not started |

## Phase 1: Git history and current tree

**Date:** 2026-09-27

### What was scanned

A `git clone --mirror` of `github.com/hjed/personal-management-system`. The mirror refspec
(`+refs/*:refs/*`) includes GitHub's pull-request refs.

| Refs | Count |
|---|---|
| Branches (`refs/heads/*`) | 603 |
| Tags (`refs/tags/*`) | 114 |
| Pull-request heads (`refs/pull/*/head`) | 1,503 |
| Pull-request merges (`refs/pull/*/merge`) | 4 |
| **Commits reachable from all refs** (`git rev-list --all --count`) | **4,742** |

- The mirror's `main` was at `42c561cf30333340bc0a47999c0efd066035931f`.
- Of the 4,742 commits, 1,261 are merges and 3,481 are not. `git log -p` (which gitleaks uses) shows
  no diff for a merge commit, and a merge cannot add content that is not in one of its parents.
- gitleaks reported **3,464 commits scanned**. The other 17 non-merge commits have no text diff
  (empty or binary-only). Of the 3,464, 3,446 add text lines and 18 only delete lines, so every
  commit that could introduce a secret was scanned.
- `refs/pull/*/merge` are GitHub's synthetic merge commits and add no new diffs.

### Tools

Both scanners ran as pinned Docker images as the invoking user, with `safe.directory` set. This
avoids git's "dubious ownership" error, which can make a scan silently check almost nothing.

| Tool | Version | Image digest |
|---|---|---|
| gitleaks | v8.30.1 | `zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f` |
| TruffleHog | 3.97.9 | `trufflesecurity/trufflehog@sha256:52e67fef4d054ecff5c2ce4b4ae376626d1ef54aa0898b53cac19c25e92e14db` |

The committed config needs gitleaks **≥ 8.25** (top-level `[[allowlists]]` with `condition` and
`targetRules`). The ITER19-001 Phase 2 hook and CI job must pin this version or newer.

### Scan runs

`D` stands for
`docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' -v <scratch>:/s -v <worktree>:/wt:ro`.
The mirror is bare, so the config is always passed explicitly. gitleaks does not find it inside a
bare repository and silently falls back to the defaults.

| # | Command | Exit | Result |
|---|---|---|---|
| 1 | `D zricethezav/gitleaks:v8.30.1 git --log-opts="--all" --redact /s/mirror.git` (default rules) | 1 | 29 findings, 3,464 commits |
| 2 | `D trufflesecurity/trufflehog:3.97.9 git --bare file:///s/mirror.git --results=verified,unknown --json --no-update` | 0 | **0 verified**, 58 unknown (verification could not connect) |
| 3 | `D zricethezav/gitleaks:v8.30.1 git --log-opts="--all" --redact -c /wt/.gitleaks.toml --gitleaks-ignore-path /wt/.gitleaksignore /s/mirror.git` | 0 | **0 findings**, 3,464 commits |
| 4 | `D zricethezav/gitleaks:v8.30.1 dir --redact -c /wt/.gitleaks.toml --gitleaks-ignore-path /wt/.gitleaksignore /s/export` (a `git archive` export of this branch) | 0 | **0 findings** |

### Coverage canaries

The canaries were run in scratch copies only and never committed.

- **Pull-request refs.** A copy of the mirror got a commit holding a made-up AWS key, reachable
  **only** from `refs/pull/99999/head` (no branch contains it).
  - gitleaks flagged it (`aws-access-token`, `generic-api-key`), with and without the committed config.
  - TruffleHog (run with `--no-verification`, so an unverifiable fake key is still listed) also reported it.
  - This proves both scanners reach pull-request refs.
- **Allowlist is not a blanket path exclusion.** With the committed config, `gitleaks dir` over a
  scratch directory flagged a made-up AWS key in each of these places:
  - a copy of `.env.test` (the key was appended);
  - a file under `backend/tests/`;
  - an ordinary source file.

  It flagged nothing among the real `.env.test` and `.env.dev` placeholders.
  - A generic high-entropy value, caught by `generic-api-key` (the rule every allowlist targets), was
    also still flagged in `tests/`, in `.env.test` and in a source file.
  - This canary caught a gitleaks 8.30 behaviour. A **global** allowlist's `paths` skip the whole
    file even under `condition = "AND"`. Every entry therefore sets `targetRules`, and
    rule-targeted allowlists honour `AND`.

### Current tree review

Each file was reviewed by hand for values that grant access.

| File(s) | Contents | Classification |
|---|---|---|
| `.env.dev` | `dev-*` / `*-change-in-production` values; Google, GitHub, Microsoft, Discord and Immich secrets empty | Placeholder |
| `.env.test` | `test-*` / `test_*` values, `postgres` DB password | Placeholder |
| `backend/.env.example`, `frontend/.env.example`, `integration_workers/{google,immich,snipeit,strava}/.env.example` | `your-*` values or empty | Placeholder |
| `docker-compose.yml` | `${VAR:-default}` fallbacks: `postgres`, `dev-*`, `dev_*_change_in_production` | Placeholder |
| `docker-compose.yml` (`ENCRYPTION_KEY` default on the google/strava/immich/snipeit workers) | A generated Fernet key, also used by `test_strava_oauth.py` and `test_strava_webhook_integration.py` | Placeholder: production sets its own `ENCRYPTION_KEY` (owner-confirmed, see [Resolved items](#resolved-items)) |
| `docker/oauth-provider/{hydra.yml,hydra-test.yml,init-oauth.sh}`, `scripts/fix-oauth-client.sh` | Local Hydra (`dev: true`), `dev-client-secret` | Placeholder |
| `docker/database/init*.sql` | No passwords | Clean |
| `.github/workflows/*` | Only `secrets.GITHUB_TOKEN` (in `release.yml`); CI service passwords `postgres` / `testpass`, `test_client_secret` | Placeholder |
| `frontend/tests/e2e/auth.setup.ts`, `frontend/tests/e2e/fixtures/*`, `backend/tests/fixtures/*`, `core_shared/core_shared/testing/fixtures.py` | No credentials; a local test DB URL | Placeholder |

There are no HTTP cassettes or HAR files. No private keys, and no Google, GitHub, AWS, OpenAI or
JWT tokens, were found in any ref.

### Findings

gitleaks run 1: 29 findings, all rule `generic-api-key`, grouped by file.

| File | First commit | Hits | Classification | Action |
|---|---|---|---|---|
| `backend/tests/integration/google_contacts/test_google_auth_service.py`, `…/test_google_contacts_client.py` | `ce2fddf9` (2025-07-20) | 4 | Placeholder: a Fernet key generated for tests, used only by these tests | Allowlisted |
| `backend/tests/unit/infrastructure/auth/test_google_oauth_service.py` | `20642be8` (2025-12-09) | 2 | Placeholder (`test_…` literal) | Allowlisted |
| `job_log.txt`, `job_log_chromium.txt` (committed CI logs) | `1d21de36` (2026-04-15) | 4 | False positive: e2e tag names `NavParent-<ts>-<n>` | Allowlisted by value shape |
| `backend/tests/integration/api/integrations/test_strava_oauth.py` | `2bf970e4` (2026-05-02) | 1 | Placeholder: a Fernet test key, also the compose dev default (see Resolved items) | Allowlisted in `tests/` only |
| `.agents/skills/playwright-skill/core/configuration.md` | `16252b27` (2026-05-24) | 1 | Placeholder (`test-key-…` doc example) | Allowlisted |
| `.agents/skills/playwright-skill/core/third-party-integrations.md` | `16252b27` (2026-05-24) | 2 | False positive: Google's publicly documented always-pass reCAPTCHA test keys | Allowlisted |
| `backend/tests/integration/integrations/test_snipeit_auth_integration.py` | `7e611c6e` (2026-05-24) | 1 | Placeholder (`test-api-key-…`) | Allowlisted |
| `backend/tests/integration/conftest.py` | `71efbbc3` (2026-05-25) | 1 | Placeholder: a Fernet test key, only in this file across history | Allowlisted |
| `integration_workers/immich/tests/integration/test_immich_api_client_integration.py` | `1eeb0a31` (2026-05-27) | 2 | Placeholder: a mock shared-link key | Allowlisted |
| `integration_workers/immich/tests/unit/test_immich_api_client.py` | `1eeb0a31` (2026-05-27) | 1 | Placeholder (`test-api-key-…`) | Allowlisted |
| `backend/tests/unit/settings/test_timezone_utils.py` | `21dcbd3d` (2026-06-07) | 1 | False positive: IANA zone name `Australia/Sydney` | Allowlisted by value shape |
| `integration_workers/{strava,immich,snipeit}/tests/integration/test_*_settings_integration.py` | `18122e11` / `83535c52` (2026-06-14) | 6 | Placeholder: base64 of `testkeytestkey…` | Allowlisted |
| `backend/tests/{integration,unit}/journal/test_journal_date_resolver.py` | `6e5c0812` (2026-08-04) | 2 | False positive: IANA zone name | Allowlisted by value shape |
| `backend/tests/unit/infrastructure/test_secret_paths.py` | `2727b653` (2026-09-17) | 1 | Placeholder: base64 of `foobar-secret-token-…` | Allowlisted |

TruffleHog run 2: 0 verified, and 58 `unknown` results, all from the `Postgres` detector. Each is a
connection URL whose verification could not reach a server. They are grouped by credential shape;
no value that is not a placeholder appears.

| Credential shape | Files (first commit) | Hits | Classification |
|---|---|---|---|
| `postgres:postgres` @ `database` / `database-test` / `db` | `docker-compose.yml` (`1056074e`), `docker-compose.test.yml` (`2ddf2408`), `docs/architecture/integration-architecture.md` (`89323a88`), `integration_workers/*/tests`, `.agents/skills/playwright-skill/ci/*` (`16252b27`) | 27 | Placeholder |
| `dev_user:dev_password` @ `postgres-dev` / `database` / `postgres` | `.env.dev`, `docker-compose.dev.yml`, `docs/troubleshooting/*` (`48dcf47a`), `docs/architecture/deployment-guide.md` (`aa602b59`) | 18 | Placeholder |
| `user:password`, `user:pw`, `user:pass`, `testuser:testpass`, `envuser:envpass` | `core_shared/tests/*` (`42d3164f`, `7992d228`, `8bc16f53`), `integration_workers/*/tests/unit/*` (`18122e11`, `83535c52`), `integration_workers/google_contacts/.env.example` (`4b9a0025`), docs | 13 | Placeholder |

gitleaks' rules don't match the Postgres URLs, so they need no allowlist entries.

### Remediation

- **Real credentials found:** 0. No rotation was needed, and `.gitleaksignore` has no entries.
- **Repository hygiene:**
  - Removed the tracked `.tmpxYhLD4` (a local MCP config holding local paths and workspace IDs, no
    credentials) and added `/.tmp*` to `.gitignore`.
  - Moved the stray root `ITER2-004-Phase2-Production-Readiness.md` to `docs/tasks/`.

### Resolved items

- **Compose default `ENCRYPTION_KEY`.** `docker-compose.yml` falls back to a generated Fernet key for
  the four integration workers, whose services include the `prod` profile. The owner confirmed on
  2026-09-27 that production sets its own `ENCRYPTION_KEY`, so the default is never used there. It
  is a dev/test placeholder.
  - A production deployment must keep setting `ENCRYPTION_KEY`. If it ever falls back to this
    default, the key must be treated as compromised and rotated.

### Gate status (Phase 1)

**✅ Met.** There are 0 real credentials in git history or the current tree, and there are no open
items.

### Re-running the audit

Mirror-clone the repository, then run scan runs 1–4 above with the same image versions. Record the
new counts here. A new finding is triaged in the table, and it is either allowlisted in
`.gitleaks.toml` (a placeholder or false positive, path + value + `targetRules`) or rotated and
fingerprinted in `.gitleaksignore` (a real credential).

## Phase 3: GitHub-side content

Not started. It will cover PR and issue bodies and comments, retained Actions logs and artifacts,
releases, any wiki, and every published GHCR image layer.
