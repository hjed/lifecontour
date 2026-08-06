---
description: Plan then implement an iteration task/phase with full TDD coverage
argument-hint: <ITER-ID> [phase N] — e.g. ITER11-003 phase 2
model: opus
---


Plan and then implement **$ARGUMENTS** using TDD. Make sure the plan includes Unit, Integration and e2e coverage. (E2E coverage can be skipped if the change does not yet impact frontend)

Start by reviewing the documents linked in the iteration doc (especially the product-specification), as well as our standards  and architecture. Then review existing components we can modify or review. Ensure we update the iteration doc with our progress as we go and include this in the plan. Also include a check step in the plan to review our changes against the product specification and itteration doc Ensure all tests specified in the spec are included as a minimum. . Ensure you test all quality gates locally. Ensure UI is accessible and follow best practises for playwright. Make sure all tests are run locally and are passing. Ensure any relevant documentation is updated.

You MUST write the plan first, using the app MCP plan tools. Author it with `set_plan`, then
call `submit_plan_for_review` and wait. Do not edit any files or run any implementation steps
until the plan has been approved. Plan mode is not used — the app plan is the only
task-tracking mechanism for this session, so do not use builtin todo or task tools.

## Phase 1 — Research (before planning)

Work through the reference material in this order, using the auggie codebase-retrieval
MCP tool for code/concept search before grep/find (per CLAUDE.md):

1. **Locate the iteration doc** for the task in `docs/tasks/` (e.g. `iteration-11-*.md`) and
   read the entry for **$ARGUMENTS**, including its acceptance criteria and every linked document.
2. **Read the linked product specification** in `docs/product-specifications/` in full —
   this is the source of truth. Note every test the spec requires; these are the *minimum*
   tests the plan must include.
3. **Review the standards & architecture** relevant to the task:
   - `CLAUDE.md` (test-first workflow, transaction management, DI, fixtures)
   - `docs/architecture.md` and the relevant `docs/architecture/*.md` (domain, API, database,
     frontend, integration, testing-strategy)
   - `docs/code-quality-standards.md`
4. **Review existing components** we can reuse, modify, or extend — backend services/repos,
   `core_shared` models/schemas, frontend components, fixtures, and helpers. Prefer reuse over
   new code (per CLAUDE.md). Identify the specific files that will change.

You can use explore-auggie, and plan subagents. DO NOT use the generic `explore` agent.

## Phase 2 — Build the plan

The plan document you write with `set_plan` MUST include:

- **Scope**: exactly what phase of **$ARGUMENTS** is in/out of scope, traced to the spec.
- **Test plan (TDD, tests written first)** with explicit coverage at all three levels:
  - **Unit tests** — backend domain/business logic and/or frontend components (per `tests/unit/`
    and frontend conventions).
  - **Integration tests** — real Docker Postgres via `tests/integration/conftest.py` fixtures
    (`async_connection`, `clean_database`, `authenticated_client`); never custom DB providers.
  - **E2E tests** — Playwright, each test creating its own deterministic data (no conditional
    logic, no skips, no multi-outcome assertions per CLAUDE.md). Validate on Mobile Chrome when
    Firefox is unsupported locally; use typing delays for ProseMirror/contenteditable; avoid
    `force: true`.
  - A checklist mapping **every test the product spec requires** to a test in this plan, so the
    spec's required tests are included as a minimum.
- **Implementation steps** ordered red → green → refactor, naming the files to change.
- **Accessibility**: ARIA, keyboard navigation, screen-reader support, and semantic color
  classes for UI work.
- **Iteration-doc updates**: a step to update the iteration doc's status/progress for
  **$ARGUMENTS** as work proceeds, and again on completion. This is part of the plan.
- **Verification / check step**: a dedicated step near the end to review the implemented changes
  back against the **product specification** and the **iteration doc**, confirming every required
  test exists and passes and every acceptance criterion is met.
- **Quality gates**: a step to run all relevant gates locally before completion —
  - backend: `ruff` format/lint + `mypy`, unit tests, and backend integration tests
    (see the `running-backend-integration-tests` skill);
  - worker changes: relevant worker integration tests (`running-worker-integration-tests` skill);
  - frontend: `pnpm quality:check` and affected tests;
  - e2e: the relevant Playwright tests locally (`running-e2e-tests` skill).
- **Documentation**: a step to update any relevant docs (architecture, API, specs, READMEs)
  touched by the change.

`set_plan` splits the plan in two: the prose above — scope, test plan, spec-test checklist,
accessibility, verification — goes in `content` for the user to read, and the ordered
implementation checklist goes in `steps`. Every requirement listed above must appear in one or
the other. Then call `submit_plan_for_review` and wait for approval.

## Phase 3 — Implement (after approval)

Once the plan is approved, execute it in TDD order, keeping exactly one step `in_progress` and
resending the full step list with `set_plan` as statuses change:

1. Write the failing tests first and confirm they fail (red).
2. Implement the minimum code to pass (green), then refactor.
3. Update the iteration doc progress as you complete each step (this is the repo's
   `docs/tasks/` doc, and is separate from the app plan). Record notes and blockers with
   `report_progress`, and refresh `report_status` after finishing each step.
4. Run **all** quality gates and the full set of relevant tests locally; fix every failure —
   do not defer. All tests must be passing before you consider the work done.
5. Perform the check step: review changes against the product spec and iteration doc, confirming
   all spec-mandated tests are present and passing and acceptance criteria are met.
6. Update relevant documentation and the iteration doc to mark the phase complete.

Report what was implemented, which tests/gates were run locally, and their results.

## Phase 4 - Review

Delegate a subagent to review our changes against the itteration doc and spec.
