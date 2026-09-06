/**
 * Driving the retarget dialog: choose a future journal, then submit it.
 *
 * Shared rather than defined per spec because both halves are retry loops that
 * exist for a reason, and a copy is a place the reason can be fixed once and
 * missed twice — which is exactly what happened: `journal-delete-blocked.spec`
 * held an inline copy of the picker loop, so the submit below had to be fixed
 * in two files or in neither.
 */

import { expect, type Locator } from '@playwright/test';

/** A journal a test created, as its data manager reports it. */
interface RetargetJournal {
  readonly id: string | number;
  readonly title: string;
}

/**
 * Choose a due journal in a `FutureJournalPicker`.
 *
 * Wrapped in `toPass` around the whole fill-then-click sequence, following
 * `journals-merge.spec.ts`: on mobile a touch-blur can dismiss the option list
 * between the two steps, and retrying half the sequence would retry the wrong
 * half. Every step is idempotent — refilling the search re-runs it, and
 * clicking an already-chosen option chooses it again — so the retry is safe.
 *
 * **Every step inside carries a short timeout of its own, the click included.**
 * `toPass` only retries what it has budget left for, and the click would
 * otherwise inherit the project's action timeout — 30s on Mobile Chrome, the
 * whole budget — so one hung click would consume the retries this exists for.
 *
 * The search is filled with the journal's title even though the option is
 * addressed by id, because the picker reads a 90-day window and the shared user
 * may hold more journals in it than one page returns.
 */
export async function chooseDueJournal(
  scope: Locator,
  journal: RetargetJournal
): Promise<void> {
  const search = scope.getByTestId('future-journal-search');
  const option = scope.getByTestId(`future-journal-option-${journal.id}`);

  await expect(async () => {
    await search.fill('', { timeout: 5000 });
    await search.fill(journal.title, { timeout: 5000 });
    await expect(option).toBeVisible({ timeout: 5000 });
    await option.click({ timeout: 5000 });
    await expect(option).toHaveAttribute('aria-selected', 'true', {
      timeout: 5000,
    });
  }).toPass({ timeout: 45000 });
}

/**
 * Submit the dialog, and hold it to the only outcome that counts: it closes.
 *
 * **The click is level-triggered because a single one can be swallowed.**
 * Observed on Firefox in CI (run 34025449574): the dialog was still open 15s
 * after a click Playwright reported as landing, with its submit button
 * *enabled* — so the mutation had neither started nor failed, and the click had
 * simply not reached the button. The picker's option list is an inline `<ul>`
 * that grows and shrinks with the search, and `keepPreviousData` holds the
 * previous, longer list until the narrowed response arrives. `aria-selected` —
 * what {@link chooseDueJournal} waits for — becomes true on the *stale* list,
 * so the footer can still jump upwards between Playwright's actionability
 * check and the click it dispatches.
 *
 * Waiting for the list to settle was the alternative and was declined: it means
 * asserting an option count, which is a claim about what else the shared user
 * holds rather than about this dialog. Retrying against the state the caller
 * actually wants makes no such claim, and covers a shift from any cause.
 *
 * **Safe to repeat.** The button is disabled while the write is in flight, so a
 * retry cannot double-submit; a click that did land closes the dialog and ends
 * the loop on the next pass. The early return is what stops that pass from
 * deadlocking — `toPass` around a click at a control that is gone would retry
 * until its whole budget expired, having already succeeded.
 */
export async function submitRetarget(dialog: Locator): Promise<void> {
  await expect(async () => {
    // Gone already: a previous attempt's click landed after all. Read only
    // *inside* the loop, where a wrong answer is corrected on the next pass —
    // and only ever reached after the caller has seen the dialog open.
    if (!(await dialog.isVisible())) return;

    await dialog.getByTestId('retarget-dialog-submit').click({ timeout: 5000 });
    await expect(dialog).toBeHidden({ timeout: 5000 });
  }).toPass({ timeout: 45000 });

  await expect(dialog).toBeHidden();
}
