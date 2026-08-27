/**
 * E2E tests for the journal delete guard, as a user meets it.
 *
 * A task is anchored to exactly two journals and can never exist without both,
 * so deleting either is refused — **whatever the task's status**, because a
 * done task's link to the journal it was created in is part of the record. The
 * specification asks that the refusal be explanatory rather than opaque: every
 * blocking task named, and each one linked to a journal where it can be
 * actioned. That is what this file drives, from the delete button through the
 * link and back.
 *
 * Two things the criterion's wording does not spell out, pinned here:
 *
 * - **Status is not the blocker.** "Cancel the task and the delete succeeds" is
 *   not how the guard works and never was; cancelling changes what the
 *   explanation *says* about a blocker, not whether it blocks. The route out is
 *   retargeting, which moves the *due* anchor and leaves the journal behind as
 *   an intermediate link — and intermediate links never block.
 * - **Merge is never refused.** The same task links that stop a delete are
 *   re-pointed by a merge, so a journal that anchors a task still absorbs into
 *   another one.
 *
 * **Every test builds its own journals and task.** The e2e user is shared, so
 * nothing asserts on data it did not create and nothing branches on what it
 * finds. Dates come from the `daysAhead`/`dayOffset` helpers, which are UTC
 * offsets: the e2e user has no configured timezone, so the backend decides what
 * "future" means by UTC days and a local wall-clock fixture can land on the
 * wrong side of the boundary the due-journal rule turns on.
 */

import type { Locator, Page } from '@playwright/test';

import { TestDataManager } from './data-management';
import { test, expect, type TestJournal } from './fixtures';

/** A task's text, made unique so a leftover row can never satisfy an assertion. */
function taskText(what: string): string {
  return `${what} ${crypto.randomUUID().slice(0, 8)}`;
}

/**
 * Open a journal and wait for its tasks card.
 *
 * The card is the right readiness marker rather than the page heading: it
 * renders nothing while the listing is in flight, so its presence is exactly
 * "this journal's tasks have loaded" — and every test here goes on to press a
 * control in the same header row.
 */
async function openJournal(page: Page, journal: TestJournal): Promise<Locator> {
  await page.goto(`/journals/${journal.id}`);
  const section = page.getByTestId('journal-tasks-section');
  await expect(section).toBeVisible();
  return section;
}

/** Press Delete and confirm it, returning the dialog for whatever follows. */
async function attemptDelete(page: Page): Promise<Locator> {
  await page.getByTestId('delete-journal-button').click();
  const dialog = page.getByTestId('delete-journal-dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByTestId('confirm-delete-journal').click();
  return dialog;
}

test.describe('Journal Delete Guard', () => {
  test('refuses a journal a task is due in, and links to where the task can be actioned', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Expedition briefing',
      dayOffset: 0,
    });
    // EVENT-typed, so the dialog's steer can name the control that cancels it.
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Permit deadline',
      daysAhead: 3,
      cancellable: true,
    });
    const text = taskText('Print the permit');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });

    await openJournal(page, dueJournal);
    const dialog = await attemptDelete(page);

    // The refusal replaces the confirmation in place. A toast would take the
    // one actionable part — the journal to open — away before it was clicked.
    const blocker = dialog.getByTestId(`journal-delete-blocker-${task.id}`);
    await expect(blocker).toBeVisible();
    await expect(blocker).toContainText(text);
    await expect(blocker).toContainText('Not done');
    await expect(blocker).toContainText('due in this journal');

    // The steer names the control, because "cancel it instead" is only
    // actionable if the user knows where the cancelled state lives.
    await expect(dialog.getByTestId('delete-journal-steer')).toContainText(
      'Event Status'
    );

    // The link goes to the *other* anchor: the journal being deleted is the
    // due one, so the task is actionable from the journal it was created in.
    const link = dialog.getByTestId(`journal-delete-blocker-link-${task.id}`);
    await expect(link).toHaveText(creatingJournal.title);
    await link.click();

    await expect(page).toHaveURL(
      new RegExp(`/journals/${creatingJournal.id}$`)
    );
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toContainText(text);
    await expect(row.getByRole('button', { name: 'Mark done' })).toBeVisible();

    // Nothing was deleted: the journal is still there to go back to.
    await openJournal(page, dueJournal);
    await expect(
      page.getByRole('heading', { name: dueJournal.title })
    ).toBeVisible();
  });

  test('names every blocking task when a journal anchors more than one', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Kit review',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Departure day',
      daysAhead: 3,
    });
    const first = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text: taskText('Service the stove'),
    });
    // Created *and* due in the same journal — one blocker holding both anchor
    // roles, which the explanation must read as one row rather than two.
    const both = await dataManager.createTask({
      creatingJournalId: dueJournal.id,
      dueJournalId: dueJournal.id,
      text: taskText('Load the trailer'),
    });

    await openJournal(page, dueJournal);
    const dialog = await attemptDelete(page);

    await expect(
      dialog.getByTestId('journal-delete-blockers').getByRole('listitem')
    ).toHaveCount(2);

    const firstRow = dialog.getByTestId(`journal-delete-blocker-${first.id}`);
    await expect(firstRow).toContainText(first.text);
    await expect(
      dialog.getByTestId(`journal-delete-blocker-link-${first.id}`)
    ).toHaveText(creatingJournal.title);

    const bothRow = dialog.getByTestId(`journal-delete-blocker-${both.id}`);
    await expect(bothRow).toContainText(both.text);
    await expect(bothRow).toContainText('created in this journal');
    await expect(bothRow).toContainText('due in this journal');
    // Both its anchors are the journal being deleted, so the only journal left
    // to send the user to is that same one.
    await expect(
      dialog.getByTestId(`journal-delete-blocker-link-${both.id}`)
    ).toHaveText(dueJournal.title);
  });

  test('still refuses once the task is cancelled — status is not what blocks', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Weekly planning',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Council meeting',
      daysAhead: 3,
    });
    const text = taskText('Draft the objection');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });

    await openJournal(page, dueJournal);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await row.getByRole('button', { name: 'Cancel task' }).click();
    await expect(row.getByText('Cancelled', { exact: true })).toBeVisible();

    const dialog = await attemptDelete(page);

    // Still refused, and the explanation says so with the new status — a
    // cancelled task blocking a delete must not read as an oversight.
    const blocker = dialog.getByTestId(`journal-delete-blocker-${task.id}`);
    await expect(blocker).toBeVisible();
    await expect(blocker).toContainText('Cancelled');
    await expect(blocker).toContainText(text);
  });

  test('retargeting the task clears the block, and the delete then succeeds', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Trip planning',
      dayOffset: 0,
    });
    const firstDue = await dataManager.createFutureJournal({
      title: 'Gear check',
      daysAhead: 3,
    });
    const secondDue = await dataManager.createFutureJournal({
      title: 'Packing night',
      daysAhead: 5,
    });
    const text = taskText('Service the stove');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: firstDue.id,
      text,
    });

    await openJournal(page, firstDue);
    const blocked = await attemptDelete(page);
    await expect(
      blocked.getByTestId(`journal-delete-blocker-${task.id}`)
    ).toBeVisible();
    await blocked.getByRole('button', { name: 'Close' }).click();
    await expect(blocked).toBeHidden();

    // Move the due anchor off this journal. What it leaves behind is an
    // *intermediate* link, which the guard does not count.
    const row = page.getByTestId(`journal-task-${task.id}`);
    await row
      .getByRole('button', { name: 'Reschedule task onto a new due journal' })
      .click();
    const retarget = page.getByRole('dialog', {
      name: 'Move this task to another journal',
    });
    await expect(retarget).toBeVisible();

    const search = retarget.getByTestId('future-journal-search');
    const option = retarget.getByTestId(
      `future-journal-option-${secondDue.id}`
    );
    await expect(async () => {
      await search.fill('', { timeout: 5000 });
      await search.fill(secondDue.title, { timeout: 5000 });
      await expect(option).toBeVisible({ timeout: 5000 });
      await option.click({ timeout: 5000 });
      await expect(option).toHaveAttribute('aria-selected', 'true', {
        timeout: 5000,
      });
    }).toPass({ timeout: 45000 });
    await retarget.getByTestId('retarget-dialog-submit').click();
    await expect(retarget).toBeHidden();

    const deleteResponse = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/journals/${firstDue.id}`) &&
        response.request().method() === 'DELETE'
    );
    await attemptDelete(page);
    expect((await deleteResponse).status()).toBe(204);

    await expect(page).toHaveURL(/\/journals$/);

    // The commitment survived the journal it used to be due in.
    await openJournal(page, secondDue);
    await expect(page.getByTestId('journal-tasks-group-due')).toContainText(
      text
    );
  });

  test('deletes a journal that only mentions a task, and the task is unaffected', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Standup notes',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Review day',
      daysAhead: 3,
    });
    const mentioning = await dataManager.createRelativeJournal({
      title: 'Corridor conversation',
      dayOffset: 0,
    });
    const text = taskText('Chase the invoice');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });
    await dataManager.attachTaskMention(task.id, mentioning.id);

    await openJournal(page, mentioning);
    await expect(
      page.getByTestId('journal-tasks-group-mentioned')
    ).toContainText(text);

    // A mention is not an anchor, so this is an ordinary delete — unchanged
    // from what it did before the guard existed.
    const deleteResponse = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/journals/${mentioning.id}`) &&
        response.request().method() === 'DELETE'
    );
    await attemptDelete(page);
    expect((await deleteResponse).status()).toBe(204);
    await expect(page).toHaveURL(/\/journals$/);

    await openJournal(page, dueJournal);
    await expect(page.getByTestId('journal-tasks-group-due')).toContainText(
      text
    );
  });

  test('merges a journal that anchors a task, which a merge never refuses', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const source = await dataManager.createRelativeJournal({
      title: 'Absorbed briefing',
      dayOffset: 0,
    });
    const target = await dataManager.createRelativeJournal({
      title: 'Surviving briefing',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Handover day',
      daysAhead: 3,
    });
    const text = taskText('Write the handover');
    const task = await dataManager.createTask({
      creatingJournalId: source.id,
      dueJournalId: dueJournal.id,
      text,
    });

    await openJournal(page, target);
    await page.getByRole('button', { name: /merge journal/i }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const combobox = dialog.getByRole('combobox');
    const option = dialog.locator('li[role="option"]', {
      hasText: source.title,
    });
    await expect(async () => {
      await combobox.clear({ timeout: 5000 });
      await combobox.fill(source.title, { timeout: 5000 });
      await expect(option).toBeVisible({ timeout: 5000 });
      await option.click({ timeout: 5000 });
      await expect(dialog.getByText('Selected to merge:')).toBeVisible({
        timeout: 5000,
      });
    }).toPass({ timeout: 45000 });

    await dialog.getByRole('button', { name: /next/i }).click();

    // The two journals have different titles, so there is always exactly one
    // conflict and the resolution step is reached deterministically. Its
    // defaults are taken as they come: which title survives is not what this
    // test is about.
    const resolution = page
      .getByRole('dialog')
      .filter({ hasText: 'Resolve Merge Conflicts' });
    await expect(resolution).toBeVisible();

    const mergeResponse = page.waitForResponse(
      response =>
        response.url().includes(`/api/journals/${target.id}/merge`) &&
        response.request().method() === 'POST'
    );
    await resolution
      .getByRole('button', { name: /resolve and merge/i })
      .click();
    expect((await mergeResponse).status()).toBe(200);
    await expect(resolution).toBeHidden();

    // The task's creating anchor was re-pointed rather than refused: it is now
    // created in the survivor, and the source is gone.
    await openJournal(page, target);
    await expect(page.getByTestId('journal-tasks-group-created')).toContainText(
      text
    );
    await expect(page.getByTestId(`journal-task-${task.id}`)).toBeVisible();

    const gone = await page.request.get(`/api/journals/${source.id}`);
    expect(gone.status()).toBe(404);
  });
});
