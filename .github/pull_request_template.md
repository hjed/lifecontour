<!--
Read CONTRIBUTING.md before opening a pull request. Fill in every section; delete nothing.
Never describe a security vulnerability here: see SECURITY.md.
-->

## Description

Brief description of the changes in this PR and why they are needed.

## Linked Issue

Closes #<!-- issue number. Required unless this is a typo or docs-only fix. -->

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)
- [ ] Performance improvement
- [ ] Test improvements

## Diff Size

Changed lines (additions + deletions, tests included; `git diff --shortstat main...HEAD`):
<!-- e.g. 3 files changed, 210 insertions(+), 40 deletions(-) -->

- [ ] This PR changes at most 500 lines, or I have explained below why it cannot be split

## Tests Run

<!-- List the commands you ran and their results. -->

- [ ] Tests were written first and fail without the change
- [ ] Pre-commit hooks pass
- [ ] Backend: `ruff`, `mypy` and the unit/integration tests for the changed code
- [ ] Frontend: `pnpm quality:check` and the affected Jest tests
- [ ] End-to-end: the affected Playwright tests
- [ ] Not applicable (explain):

## AI Assistance

- [ ] No AI tools were used for this change
- [ ] AI tools were used. Tools: <!-- e.g. Claude Code, Copilot -->
  - [ ] I reviewed every AI-generated line and take responsibility for it
  - [ ] Automated code review was run and its findings addressed

## Contributor Checklist

- [ ] I have read [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md), and this branch is rebased on `main` (no merge commits)
- [ ] I have signed, or will sign when the bot asks, the [Contributor License Agreement](../blob/main/CLA.md), and I license this contribution under its terms
- [ ] Relevant documentation is updated

## Maintainer Checklist

- [ ] `secret-scan` passed on this head (bottom layer or dispatched)
