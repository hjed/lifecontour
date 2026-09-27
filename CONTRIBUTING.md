# Contributing

Copyright (C) 2025–2026 Harry J E Day

Thank you for your interest in contributing. This project has a single maintainer and is developed
with a lot of AI assistance, so the rules below keep every change small, reviewable and traceable.
Please read them before you open an issue or a pull request.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licensing of contributions

The project is licensed under the GNU Affero General Public License, version 3 or later
(`AGPL-3.0-or-later`; see [LICENSE](LICENSE)), together with the additional permissions in
[LICENSE-EXCEPTIONS.md](LICENSE-EXCEPTIONS.md).

Contributions are accepted under those same terms **plus** the
[Contributor License Agreement](CLA.md):

- You keep the copyright in your contribution. The CLA is a licence grant, not an assignment.
- The CLA gives the maintainer a broad licence to your contribution, including the right to
  relicense it. This keeps the option to relicense or commercialise the project later.
- You sign the CLA once, on your first pull request. The CLA Assistant bot comments on the pull
  request with a link, and its status check blocks the merge until you have signed.

The project name and logo are not covered by the AGPL; see [TRADEMARKS.md](TRADEMARKS.md).

## Reporting security issues

**Never report a vulnerability in a public issue or pull request.** Follow
[SECURITY.md](SECURITY.md) and use GitHub's private vulnerability reporting.

## 1. Discuss first

Open an issue before you write code:

- For a feature or a behaviour change, use the **Feature proposal** template. Describe the problem,
  the change you want to make, and roughly how big it is.
- For a bug, use the **Bug report** template.
- Wait for the maintainer to acknowledge the issue before starting work. **Pull requests without a
  linked, acknowledged issue may be closed.**

**Exempt:** typo fixes and documentation-only fixes can go straight to a pull request.

## 2. Keep pull requests small

- A pull request changes **at most 500 lines** (additions plus deletions, tests included), so it
  can be reviewed properly. Check with `git diff --shortstat main...HEAD`.
- Split larger work into a series of pull requests, each green and deployable on its own.
  - **Contributors working from a fork:** submit dependent changes as **sequential** pull requests
    against `main`. Open the next one once the previous one has merged. A fork cannot build a stack
    upstream, because a pull request's base must be a branch in this repository.
  - **Maintainers** use native stacked pull requests on upstream branches (see
    [Stacked pull requests and CI](#stacked-pull-requests-and-ci)). If a fork contribution needs to
    be stacked, the maintainer pushes the layers to upstream branches first.
- Generated files (lockfiles, for example) count towards the limit. Mention in the pull request if
  they push it over and cannot be split.

## 3. AI-assisted contributions

AI-assisted contributions are welcome, with these conditions:

- **Review it yourself.** Review every AI-generated line personally before you submit. You are
  responsible for the whole change, as if you had written it by hand.
- **Run automated review.** Run an automated code review (for example an AI review tool) over the
  change before you open the pull request, and address what it finds.
- **Run the quality gates.** Run the pre-commit hooks, linting, type checking and tests described
  below.
- **Disclose it.** Tick the AI-assistance boxes in the pull request template and say which tools you
  used.
- **Agents follow [AGENTS.md](AGENTS.md).** It holds the project context, architecture pointers and
  development rules for coding agents. (`CLAUDE.md` is a link to it.)

## 4. Development workflow

- **Test first.** Write the failing tests, make them pass, then refactor. See the
  [Testing Strategy](docs/architecture/testing-strategy.md) for which tests go where (unit,
  integration against Docker PostgreSQL, and Playwright end-to-end).
- **Rebase, never merge.** Keep your branch up to date with `git rebase main` (or
  `git pull --rebase`). Never merge `main` into a pull request branch.
- **Pre-commit hooks.** Install them once, and let them run on every commit:

  ```bash
  ./scripts/dev.sh setup                 # creates backend/.venv and installs frontend deps
  cd backend && uv run pre-commit install
  ```

  The hooks format and lint the code and run the gitleaks secret scan. Do not bypass them with
  `--no-verify`.
- **Follow the architecture.** Start from [docs/architecture.md](docs/architecture.md) and the
  guides it links. Reuse existing code, fixtures and helpers rather than adding new ones.

### Quality commands

Every one of these must pass before you open a pull request. The full set of standards is in
[Code Quality Standards](docs/code-quality-standards.md).

```bash
# Everything CI lints (backend, core_shared, frontend)
./scripts/dev.sh lint

# All pre-commit hooks over the whole tree
./scripts/dev.sh precommit

# Backend
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run pytest tests/unit/
uv run pytest tests/integration/     # needs Docker; see backend/INTEGRATION_TESTS.md

# Frontend
cd frontend
pnpm quality:check                   # Prettier, ESLint and TypeScript
pnpm test                            # Jest + React Testing Library
pnpm test:e2e                        # Playwright; see docs/architecture/testing-strategy.md
```

Integration workers (`integration_workers/*`) have their own commands, listed in the
[Code Quality Standards](docs/code-quality-standards.md#integration-workers-python).

## 5. Opening the pull request

- Fill in every section of the pull request template: the linked issue, the diff size, the tests you
  ran, and the AI-assistance disclosure.
- Keep the description focused on what changed and why.
- Sign the CLA when the bot asks, on your first pull request.
- Expect review comments, both from the maintainer and from automated reviewers. Push follow-up
  commits, or rebase, to address them.

### Stacked pull requests and CI

**Only the bottom layer of a pull request stack runs CI.** This is deliberate, to save Actions
budget. Pull requests from forks always target `main`, so they are never an upper layer: each runs
the full CI once the maintainer approves the first workflow run.

- The maintainer runs CI on an upper layer by hand: `gh workflow run ci.yml --ref <branch>`.
- **No layer merges without a passing `secret-scan` run on its head**, either as the bottom layer
  or through that manual dispatch. The maintainer confirms this in the pull request checklist.

The details are in [CI/CD Setup → Stacked PRs](docs/ci-cd-setup.md#stacked-prs).

## Questions

If something here is unclear, open an issue and ask.
