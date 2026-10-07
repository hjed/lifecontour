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
| Phase 3 | GitHub-side content (PR/issue text, Actions logs and artifacts, releases, GHCR layers) | ✅ Complete: 0 real credentials, gate met at the cutoff |
| Phase 4 | Pre-flip delta rescan of everything after the Phase 3 cutoff; the final release gate | Not started |

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

**Date:** 2026-09-29 to 2026-10-01

This phase covers the content GitHub holds outside git. The public flip reveals all of it, and the
Phase 1 scans never saw it.

### Cutoff

Everything created up to this cutoff was scanned. ITER19-001 Phase 4 rescans anything newer before
the flip (see [Re-running](#re-running-and-the-pre-flip-delta-rescan)).

| Surface | Cutoff |
|---|---|
| PR and issue text, comments, edits | Exported 2026-09-29T11:34:18Z; newest item 2026-09-28T23:30:04Z |
| Actions runs | Listed 2026-09-29; newest run ID `36498328009` (2026-09-28T23:30:05Z) |
| Actions artifacts | Newest artifact ID `10928618934` (2026-09-27T10:25:01Z) |
| GHCR | Enumerated 2026-10-01; newest version 2026-09-27T05:43:41Z; highest version ID `1300319802` |

### What was scanned

| Surface | Scope | Count |
|---|---|---|
| Issue and PR titles and bodies | `issues?state=all` (PRs included) | 1,594 (68 issues, 1,526 PRs) |
| Conversation comments | `issues/comments` | 4,180 |
| PR review comments | `pulls/comments` | 5,272 |
| PR review bodies | GraphQL `reviews` | 3,098 reviews, 1,712 with a body |
| **Edit history** (public, shows text removed by an edit) | GraphQL `userContentEdits { diff }` on every edited body, comment and review | 2,428 edited items, 6,130 revisions |
| Title renames | GraphQL `RenamedTitleEvent` | 65 |
| Check-run output (SonarCloud, Greptile, Augment, our own) | `commits/{sha}/check-runs`, every PR head SHA | 22,916 check runs over 1,526 SHAs; 0 commit statuses |
| Commit and tag messages (Phase 1 scanned diffs only) | A fresh mirror: `git log --all --format=%B`; annotated tag objects | 4,790 commits; 115 tags, all lightweight |
| Actions run logs | `runs/{id}/attempts/{n}/logs`, every attempt of every run | 7,311 runs, 7,520 attempts: 418 retrieved (263 with content, 155 empty), 6,893 expired (`410`), 209 never had logs (`404`: skipped, cancelled or startup failures) |
| Actions artifacts | Every artifact, extracted recursively | 136: 99 Playwright reports, 36 buildx `.dockerbuild` records, 1 Bandit report |
| Releases | Notes and assets | 115 releases, 0 assets, 0 drafts |
| GHCR | Every version (tagged and untagged) of every package in the namespace | 8 container packages, 2,482 versions → 830 indexes and 1,652 manifests → 6,763 unique blobs: 1,520 configs, 830 attestations, 1 empty, 4,412 layers (88.5 GB). The layers hold 11,481,046 files, 414,087 of them unique (35.7 GB), all scanned |
| Wiki, Discussions, Pages, Projects | Repository settings, GraphQL `projectsV2` | Disabled, or 0 projects |
| Commit comments | `repos/…/comments` | 0 |

Two settings matter for the counts:

- **Log retention is 10 days** (`actions/permissions/artifact-and-log-retention`), so most logs are
  gone. Every run was still tried, because a few older runs kept their logs.
- **Packages not built by the current workflow are included**: the retired
  `personal-management-system-google-contacts-worker` (57 versions) and `-python-base`. No npm,
  Maven, RubyGems or NuGet packages exist.

### Method

- **Export, then unpack everything.**
  - Each body, comment, review, revision, release note and check output is written to its own
    file as unescaped text, as well as the JSON export. A PEM key inside a JSON string has escaped
    newlines, which the private-key rules miss.
  - Logs and artifacts are extracted recursively before scanning: zips, gzip, tar, the nested
    `trace.zip`, the base64 zip that Playwright embeds in `index.html`, and the OCI blobs inside a
    `.dockerbuild`. gitleaks `dir` does not open archives by default (`--max-archive-depth` is 0),
    and TruffleHog skips archives over its size and time limits without saying so.
- **GHCR by unique blob.**
  - Every version's manifest is resolved through the registry API. Indexes are resolved to their
    child manifests, which include buildx's provenance attestation manifests.
  - Each unique blob is fetched once and its digest is checked. That gives 1,520 image configs,
    830 in-toto attestations, 1 empty blob and 4,412 layers (88.5 GB compressed).
  - Configs (ENV, labels, build history) and attestations (build arguments) are scanned as raw
    JSON.
  - Layers are streamed in batches. Each regular file is hashed, and only the first copy of a file
    across all layers is written for scanning. A file with the same bytes produces the same
    findings, so identical dependency files rebuilt in every version are scanned once.
  - Each layer is scanned on its own, so a file that a later layer deletes is still seen.
- **Scanners:** the same pinned images as Phase 1, on every surface:
  - gitleaks with the committed `.gitleaks.toml`, plus a second run with the default rules (no
    config in the target root);
  - TruffleHog with verification on and `--results=verified,unknown,unverified`, so a key it
    cannot verify is still reported.
- **Cross-check:** `trufflehog docker --image ghcr.io/hjed/<package>@sha256:<digest>` on the
  newest tagged version of each of the 8 packages. This is the task's suggested command, run by
  digest. It covers one platform of one version, so it confirms the blob pipeline rather than
  replacing it.

### Coverage canaries

Fake credentials were made for the canaries: a randomised `AKIA…` key with a secret, and a freshly
generated RSA key. They were placed in scratch copies only, and scanned with the same flags as the
real runs. Both scanners flagged every placement, and both gitleaks runs did too:

- a raw comment file (PEM);
- the JSON comment export;
- an unzipped log;
- a `trace.zip` inside an artifact zip;
- the base64 zip embedded in a Playwright `index.html`;
- a gzip blob inside a `.dockerbuild`;
- a layer `.tar.gz` (also through the GHCR pipeline's own extractor);
- an image config `Env`.

### Findings

TruffleHog **verified 0** credentials on every surface. Every unverified result and every gitleaks
finding falls into one of the classes below. Each class was confirmed in bulk by a script over the
reports, which checks each hit's surrounding text, never by sampling. No values are recorded.

| Surface | Scanner and rule | Hits | Classification |
|---|---|---|---|
| PR and issue text and edit history | gitleaks `sourcegraph-access-token` (any 40-hex string) | 3,968 | False positive: git commit SHAs. 3,362 sit in GitHub commit or compare URLs, 352 in Dependabot "Commits" lists (`<li><sha> …`), and 254 are JSON duplicates of those |
| | TruffleHog `GitHubOauth2` | 429 | False positive: in the JSON export, a contributor handle after an escaped `\n` (or a SHA prefix) matched as the "client ID", and a commit SHA as the "secret" |
| | TruffleHog `URI` | 24 | False positive: an upstream release note's example `https://user:p%40ss@host` |
| | TruffleHog `Strava` / `Postgres` | 4 / 3 | Placeholder: test activity IDs; `postgres:postgres` and `user:pw` from test fixtures (the Phase 1 shapes) |
| Actions logs | gitleaks default `generic-api-key` | 164 | False positive: e2e tag names `NavParent-<ts>` / `NavChild-<ts>`, already allowlisted by value shape (the committed config reports 0) |
| | TruffleHog `Dockerhub` | 116 | False positive: buildx builder names (UUIDs) |
| Actions artifacts | gitleaks default `generic-api-key` | 98 | False positive: the same e2e tag names in Playwright report output (the committed config reports 0) |
| | TruffleHog `Box`, `TLy`, `Teletype`, `Aiven`, `Miro`, `Juro`, `Qase`, `UnifyID` | 124 | False positive: substrings of base64 data (embedded images and trace data) or a `sha256:` digest in a buildx log |
| GHCR configs | gitleaks `generic-api-key` | 204 | False positive: `ENV GPG_KEY`, inherited from the official `python:*-slim` base. It is the public fingerprint of the Python release-signing key, identical to `python:3.12-slim` |
| GHCR attestations | — | 0 | Clean |
| GHCR layers | gitleaks `generic-api-key`, `private-key`, `sourcegraph-access-token`, `curl-auth-header`; TruffleHog (22 detectors, mostly `Circle`, `FlatIO`, `Box`, `Alchemy`) | 457 / 13,291 | False positive, third-party content: the dependency trees (`site-packages`, `node_modules`, the `uv` and `pnpm` caches and stores), OS packages (`/usr`, `dpkg`, Alpine `APKINDEX`) and the Node base image's yarn. These are libraries' own test keys, PEM-parsing code, doc examples and base64 or index data. None is in our own packages (`core_shared`, `personal_management_*`, the workers) |
| | gitleaks `generic-api-key`; TruffleHog `Parsers`, `Box`, `Atera` | 8 / 117 | False positive: binary build caches (`.next/cache/{webpack,turbopack}`, `/tmp/node-compile-cache`) |
| | TruffleHog `Postgres` | 10 | Placeholder: `user:pw@dbhost` in the worker and `core_shared` unit tests, and `postgres:postgres` in the frontend's `.env.example` (the Phase 1 shapes) |
| | gitleaks `generic-api-key` | 610 | **Next.js build-generated keys.** See [the next section](#nextjs-build-generated-keys) |
| GHCR cross-check (`trufflehog docker`, 8 images) | TruffleHog | 664 | 0 verified. The same classes as the layer scan (third-party, binary caches, test placeholders), which confirms the blob pipeline |

GitHub's log masking was active: the retrieved logs contain 12,619 `***` redactions.

### Next.js build-generated keys

Every frontend image carries keys that `next build` generates at random for that build:

- `previewModeSigningKey` and `previewModeEncryptionKey`, in `.next/prerender-manifest.json` and
  `.next/cache/.previewinfo`;
- the Server Actions `encryptionKey`, in `.next/server/server-reference-manifest.json` and
  `.next/cache/.rscinfo`.

They are not provider credentials, but they are secret to the deployment that runs that image.
Publishing an image therefore publishes its keys.

- **What they protect:**
  - The preview keys sign and encrypt draft-mode (preview) data.
  - The Server Actions key encrypts the variables a Server Action closes over.
- **Exposure:** the app uses neither feature. `frontend/src` has no `"use server"`, `draftMode` or
  `previewData`. Knowing the keys gives nothing to forge or decrypt.
- **Can they be disabled?** No. Every `next build` writes them, and the App Router has no switch
  to turn off Server Actions or draft mode.
  - The Server Actions key can be overridden: at runtime Next.js reads
    `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` first and falls back to the baked-in key only when the
    variable is unset.
  - The preview keys have no runtime override. They protect only data that `draftMode().enable()`
    creates, and the app never calls it. Holding the manifest lets a client send a
    `__prerender_bypass` cookie, which makes prerendered pages render on demand. It exposes no
    data, because authenticated data still needs a session.
- **Decision (owner, 2026-10-01):** accepted. They are not credentials and guard unused features,
  so they do not block the gate. ITER19-005 Phase 1b
  ([#1661](https://github.com/hjed/personal-management-system/issues/1661)) hardens the frontend
  image before the packages go public:
  - set `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` from the production environment, so no baked-in key is
    ever used (including those in images already published);
  - build a multi-stage `standalone` image. It drops `.next/cache` (which holds second copies in
    `.previewinfo` and `.rscinfo`), the dev dependencies and the pnpm store.
  - **Implemented** in Phase 1b. The runner stage of `docker/frontend/Dockerfile` ships only
    the standalone output, and `start.sh` refuses to start without the key. CI's `frontend-image`
    job runs `docker/frontend/verify-image.sh`, which checks both. See
    [Deployment Guide → Frontend Image](../architecture/deployment-guide.md#frontend-image).
    ITER19-001 Phase 4 still confirms the released image and the production setting.
  - The published image no longer carries the cache, but `release.yml` builds with
    `cache-to: type=gha,mode=max`, so the `builder` stage, `.next/cache` included, still reaches
    the Actions cache on every release. Fork PRs cannot restore caches written on a tag ref, and
    the ITER19-005 Phase 2 cache purge clears the existing ones.

### Residual risks

- **Screenshots and videos** in the Playwright artifacts (91 images, 2 videos) cannot be
  text-scanned. They show the e2e app with test data and test users only.
- **Actions caches** (139 caches, 4.2 GB, including buildx `type=gha` layer caches) were not
  scanned. Once the repository is public, fork-PR workflows can restore base-branch caches.
  Decision: purge every cache just before the flip (an ITER19-005 Phase 2 pre-flip item). They
  rebuild on the next CI run.
- **Images ship build caches**: `/root/.cache/uv`, the pnpm store and `.next/cache`. They hold
  only dependency and build output, and the scans found nothing of ours in them apart from the
  Next.js keys above. ITER19-005 Phase 1b removes them from the frontend image; trimming the Python
  images is image-size hygiene, not a release blocker.

### Remediation

- **Real credentials found:** 0. Nothing needed rotating, and nothing was deleted (no run log,
  artifact, comment revision or package version).

### Gate status (Phase 3)

**✅ Met at the cutoff.**

- There are 0 real credentials on any GitHub-side surface, and TruffleHog verified 0.
- The only open items are the pre-flip actions:
  - the delta rescan, which is ITER19-001 Phase 4 and the final gate;
  - the frontend image hardening, ITER19-005 Phase 1b;
  - the Actions cache purge, an ITER19-005 Phase 2 pre-flip step.

### Re-running and the pre-flip delta rescan

The export and scan scripts were one-off tools. The procedure is:

1. **Text:**
   - Paginate `issues?state=all`, `issues/comments` and `pulls/comments`.
   - Use GraphQL for reviews, `lastEditedAt` and renames, then fetch `userContentEdits { diff }`
     for each edited node by ID.
   - Fetch check runs for each PR head SHA.
   - Write one unescaped file per item.
2. **Actions:**
   - List runs in weekly `created=` windows; a filtered list stops at 1,000 results.
   - Fetch `runs/{id}/attempts/{n}/logs` for every attempt, and every artifact zip.
   - Extract recursively.
3. **GHCR:**
   - List `/user/packages` for every package type, and every version of each package.
   - Resolve the manifests, fetch each unique blob, and stream the layers with file-hash dedupe.
4. **Scan and triage:**
   - Run the canary set first.
   - Scan with gitleaks (committed config and default rules) and TruffleHog
     (`verified,unknown,unverified`).
   - Triage by the classes above.

For the delta rescan (ITER19-001 Phase 4), restrict each step to content newer than
[the cutoff](#cutoff). That means
items created or edited since then, runs and artifacts with higher IDs, and package versions with
higher IDs, including the `lifecontour-*` packages. Then record the counts in a new section.
