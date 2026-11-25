/**
 * E2E tests for the journal task surface.
 *
 * A journal is one of only two places a task is *worked with*, and the other —
 * the dashboard — is a later iteration. So this file covers the whole loop the
 * specification describes: capture a commitment in the journal it arose in,
 * defer it, complete it, let it lapse, and bring it back.
 *
 * **Every test builds its own journals and tasks.** The e2e user is shared, so
 * nothing here may assert on data it did not create, and nothing may branch on
 * what it finds. Where a test needs the *absence* of data — the empty picker —
 * it clears the relevant window rather than hoping.
 *
 * **Dates are UTC offsets, never local wall-clock times.** The e2e user has no
 * configured timezone, so the backend decides what "future" means by UTC days;
 * a fixture built from a local midday can land on the wrong side of the
 * boundary the whole feature turns on. `utcDayOffset` is the only source of a
 * date in this file.
 */

import type { Locator, Page } from '@playwright/test';

import type { JournalDeletePreviewResponse } from '../../src/types/journals';
import type { TaskReadResponse } from '../../src/types/tasks';
import { TestDataManager, utcDayOffset } from './data-management';
import { test, expect, type TestJournal } from './fixtures';
import { chooseDueJournal, submitRetarget } from './utils/retarget-dialog';

/** A task's text, made unique so a leftover row can never satisfy an assertion. */
function taskText(what: string): string {
  return `${what} ${crypto.randomUUID().slice(0, 8)}`;
}

/**
 * Open a journal and wait for its tasks card.
 *
 * The card is the right readiness marker rather than the page heading: it
 * renders nothing at all while the listing is in flight, so its presence is
 * exactly "this journal's tasks have loaded".
 */
async function openJournal(page: Page, journal: TestJournal): Promise<Locator> {
  await page.goto(`/journals/${journal.id}`);
  const section = page.getByTestId('journal-tasks-section');
  await expect(section).toBeVisible();
  return section;
}

/**
 * On a phone the page still fits — nothing widens it sideways — and nothing
 * on it threw along the way.
 */
async function expectFitsPhoneWithoutErrors(
  page: Page,
  pageErrors: readonly Error[]
): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      )
    )
    .toBe(true);
  expect(pageErrors).toEqual([]);
}

/**
 * Name a journal in the attach dialog's journal search.
 *
 * The same retry reasoning as {@link chooseDueJournal}, over a different
 * combobox: this one searches every journal rather than only future ones, and
 * reports its choice by writing the title into its own input.
 */
async function chooseSourceJournal(
  dialog: Locator,
  journal: TestJournal
): Promise<void> {
  const search = dialog.getByLabel('Journal the task is on');
  const option = dialog.locator('li[role="option"]', {
    hasText: journal.title,
  });

  await expect(async () => {
    await search.fill('', { timeout: 5000 });
    await search.fill(journal.title, { timeout: 5000 });
    await expect(option).toBeVisible({ timeout: 5000 });
    await option.click({ timeout: 5000 });
    await expect(search).toHaveValue(journal.title, { timeout: 5000 });
  }).toPass({ timeout: 45000 });
}

test.describe('Journal Task Surface', () => {
  test('creates a task from a journal, grouped as created here and due there', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Committee meeting',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Permit deadline',
      daysAhead: 2,
    });
    const text = taskText('Print the permit');

    const section = await openJournal(page, creatingJournal);
    await expect(
      section.getByText('No tasks are linked to this journal yet.')
    ).toBeVisible();

    await section.getByTestId('journal-task-action-create').click();
    const dialog = page.getByRole('dialog', { name: 'New task' });
    await expect(dialog).toBeVisible();

    // The dialog says where focus goes rather than leaving it to Radix, so the
    // promise is worth holding it to.
    const textField = dialog.getByTestId('create-task-text');
    await expect(textField).toBeFocused();

    await textField.fill(text);
    await chooseDueJournal(dialog, dueJournal);
    await dialog.getByTestId('create-task-dialog-submit').click();
    await expect(dialog).toBeHidden();

    // The journal it was written in shows it under *created*, and names the
    // journal it comes due in, because that is the half this view is missing.
    const createdGroup = page.getByTestId('journal-tasks-group-created');
    await expect(
      createdGroup.getByRole('heading', { name: 'Created in this journal' })
    ).toBeVisible();
    await expect(createdGroup.getByTestId('journal-task-text')).toHaveText(
      text
    );
    await expect(
      createdGroup.getByRole('link', { name: dueJournal.title })
    ).toBeVisible();
    await expect(page.getByTestId('journal-tasks-group-due')).toBeHidden();

    // The journal it comes due in shows the same commitment under *due*.
    await openJournal(page, dueJournal);
    const dueGroup = page.getByTestId('journal-tasks-group-due');
    await expect(
      dueGroup.getByRole('heading', { name: 'Due in this journal' })
    ).toBeVisible();
    await expect(dueGroup.getByTestId('journal-task-text')).toHaveText(text);
    await expect(page.getByTestId('journal-tasks-group-created')).toBeHidden();
  });

  test('ticks a task done from the journal it was created in', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Morning stand-up',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Client review',
      daysAhead: 2,
    });
    const text = taskText("Return Sarah's book");
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });

    await openJournal(page, creatingJournal);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();

    // Addressed by accessible name: "Done" is what the button says, and "Mark
    // done" is what it does.
    const actions = row.getByRole('group', { name: 'Task actions' });
    await actions.getByRole('button', { name: 'Mark done' }).click();

    await expect(row.getByText('Done', { exact: true })).toBeVisible();
    await expect(
      actions.getByRole('button', { name: 'Return to not done' })
    ).toBeVisible();

    // The status flips optimistically, so the reload is what proves the change
    // was written rather than merely drawn.
    await openJournal(page, creatingJournal);
    await expect(row.getByText('Done', { exact: true })).toBeVisible();
  });

  test('retargets a task and keeps the journal it left as a mention', async ({
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
      daysAhead: 2,
    });
    const secondDue = await dataManager.createFutureJournal({
      title: 'Departure day',
      daysAhead: 4,
    });
    const text = taskText('Service the stove');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: firstDue.id,
      text,
    });

    await openJournal(page, firstDue);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(page.getByTestId('journal-tasks-group-due')).toContainText(
      text
    );

    // A live task being moved is a *reschedule*; the same control is worded as
    // a resurrect or a reopen elsewhere, which is why the name is asserted.
    await row
      .getByRole('button', { name: 'Reschedule task onto a new due journal' })
      .click();
    const dialog = page.getByRole('dialog', {
      name: 'Move this task to another journal',
    });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId('retarget-task-text')).toHaveText(text);
    await expect(dialog.getByTestId('retarget-keeps-previous')).toBeVisible();

    await chooseDueJournal(dialog, secondDue);
    await submitRetarget(dialog);

    // The model's one automatic link: the journal it was due in keeps it as a
    // mention, so the trail of a deferred commitment stays visible.
    const mentioned = page.getByTestId('journal-tasks-group-mentioned');
    await expect(
      mentioned.getByRole('heading', { name: 'Mentioned in this journal' })
    ).toBeVisible();
    await expect(mentioned).toContainText(text);
    await expect(page.getByTestId('journal-tasks-group-due')).toBeHidden();

    // And the journal it moved to now carries it as due.
    await openJournal(page, secondDue);
    await expect(page.getByTestId('journal-tasks-group-due')).toContainText(
      text
    );
  });

  test('attaches an existing task as a mention and detaches it again', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const sourceJournal = await dataManager.createRelativeJournal({
      title: 'Phone call with the office',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Site visit',
      daysAhead: 2,
    });
    const hostJournal = await dataManager.createRelativeJournal({
      title: 'Team catch-up',
      dayOffset: 0,
    });
    const text = taskText('Chase the signed contract');
    const task = await dataManager.createTask({
      creatingJournalId: sourceJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });

    const section = await openJournal(page, hostJournal);
    await expect(
      section.getByText('No tasks are linked to this journal yet.')
    ).toBeVisible();

    await section.getByTestId('journal-tasks-attach').click();
    const dialog = page.getByRole('dialog', {
      name: 'Attach an existing task',
    });
    await expect(dialog).toBeVisible();

    await chooseSourceJournal(dialog, sourceJournal);
    const option = dialog.getByRole('radio', { name: text });
    await option.click();
    await expect(option).toBeChecked();
    await dialog.getByTestId('attach-dialog-submit').click();
    await expect(dialog).toBeHidden();

    const mentioned = page.getByTestId('journal-tasks-group-mentioned');
    await expect(mentioned).toContainText(text);

    // A mention is the one link the specification lets a journal remove; the
    // anchors can only be replaced.
    const row = page.getByTestId(`journal-task-${task.id}`);
    await row
      .getByRole('button', { name: 'Remove mention from this journal' })
      .click();
    await expect(row).toBeHidden();
    await expect(
      section.getByText('No tasks are linked to this journal yet.')
    ).toBeVisible();

    // Removing the mention leaves the task itself alone, on the journals that
    // anchor it.
    await openJournal(page, sourceJournal);
    await expect(page.getByTestId('journal-tasks-group-created')).toContainText(
      text
    );
  });

  test('marks a task lapsed once its due journal moves into the past, and resurrects it', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Weekly review',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Dentist appointment',
      daysAhead: 2,
    });
    const rescueJournal = await dataManager.createFutureJournal({
      title: 'Next weekly review',
      daysAhead: 5,
    });
    const mentionJournal = await dataManager.createPastJournal({
      title: 'Corridor conversation',
      daysAgo: 1,
    });
    const text = taskText('Take the referral letter');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });
    await dataManager.attachTaskMention(task.id, mentionJournal.id);

    // The lapsed fixture recipe, and the assertion that keeps it working. No
    // task call can produce a lapsed task — both write paths refuse a past due
    // journal — so the *journal* moves instead. Journal update deliberately does
    // not re-validate task invariants; if it ever started to, this expectation
    // fails loudly instead of the test below quietly asserting nothing.
    const moved = await dataManager.moveJournalToPast(dueJournal.id, 3);
    expect(moved.status()).toBe(200);

    await openJournal(page, creatingJournal);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row.getByTestId('journal-task-lapsed')).toHaveText(
      'Lapsed · date passed'
    );
    // Lapsing marks a live commitment; it never disables one.
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();

    // "They remain visible on every journal they are linked to — creating, due,
    // and intermediate — clearly marked as lapsed." A lapsed task is met again
    // on whichever of its journals the user next opens, so **all three** roles
    // are checked: a regression that dropped the marker from only one group
    // would otherwise pass on the strength of the other two.
    await openJournal(page, mentionJournal);
    await expect(
      page
        .getByTestId('journal-tasks-group-mentioned')
        .getByTestId('journal-task-lapsed')
    ).toHaveText('Lapsed · date passed');

    // The due journal is the one the date passed *on*, and the group a user is
    // likeliest to meet the task in.
    await openJournal(page, dueJournal);
    await expect(
      page
        .getByTestId('journal-tasks-group-due')
        .getByTestId('journal-task-lapsed')
    ).toHaveText('Lapsed · date passed');

    await openJournal(page, creatingJournal);

    await row
      .getByRole('button', { name: 'Resurrect task onto a new due journal' })
      .click();
    const dialog = page.getByRole('dialog', {
      name: 'Resurrect this lapsed task',
    });
    await expect(dialog).toBeVisible();

    await chooseDueJournal(dialog, rescueJournal);
    await submitRetarget(dialog);

    await expect(row.getByTestId('journal-task-lapsed')).toBeHidden();
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();
    await expect(
      row.getByRole('link', { name: rescueJournal.title })
    ).toBeVisible();
  });

  test('marks a task lapsed when its due journal is cancelled, and says so', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Conference planning',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Conference keynote',
      daysAhead: 2,
      cancellable: true,
    });
    const text = taskText('Rehearse the opening');
    const task = await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text,
    });

    // The second cause of a lapse, and the second half of the recipe: cancelling
    // a journal is an edit to an event's participation state, and it is likewise
    // permitted while a task is due in it.
    const cancelled = await dataManager.cancelJournal(dueJournal.id);
    expect(cancelled.status()).toBe(200);

    await openJournal(page, creatingJournal);
    const marker = page
      .getByTestId(`journal-task-${task.id}`)
      .getByTestId('journal-task-lapsed');

    // The two causes must stay distinguishable — a commitment whose event was
    // called off is a different situation from one the user let slide.
    await expect(marker).toHaveText('Lapsed · journal cancelled');
    await expect(marker).toHaveAttribute(
      'title',
      "Lapsed: this task's due journal was cancelled."
    );

    // And on the cancelled journal itself, which is where the user is most
    // likely to be standing when they call the event off.
    await openJournal(page, dueJournal);
    await expect(
      page
        .getByTestId('journal-tasks-group-due')
        .getByTestId('journal-task-lapsed')
    ).toHaveText('Lapsed · journal cancelled');
  });

  test('says plainly that there are no future journals, and offers to create one', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    // The empty picker is the absence of data, which no amount of creating can
    // produce on a shared user: every journal dated today or later has to go.
    await dataManager.clearFutureJournals();
    const journal = await dataManager.createRelativeJournal({
      title: 'A day with nothing ahead of it',
      dayOffset: 0,
    });

    const section = await openJournal(page, journal);
    await section.getByTestId('journal-task-action-create').click();
    const dialog = page.getByRole('dialog', { name: 'New task' });
    await expect(dialog).toBeVisible();

    await expect(dialog.getByTestId('future-journal-empty')).toContainText(
      'No journals dated in the next 90 days'
    );
    await expect(
      dialog.getByTestId('future-journal-options').getByRole('option')
    ).toHaveCount(0);

    // "Say so plainly **and** offer to create one." The offer opens a new tab
    // on purpose, so the half-written task survives being sent away.
    const offer = dialog.getByTestId('future-journal-create-offer');
    await expect(offer).toBeVisible();
    await expect(offer).toHaveRole('link');
    await expect(offer).toHaveAttribute('href', '/journals/new');
    await expect(offer).toHaveAttribute('target', '_blank');
    await expect(offer).toContainText('opens a new tab');

    // The picker reports its emptiness to a screen reader too, and that line is
    // the whole of what a user who cannot see the list is told.
    await expect(dialog.getByTestId('future-journal-count')).toHaveText(
      'No future journals to choose from'
    );
  });

  test('shows a tasks-due indicator on the journal a task is due in, and only there', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const creatingJournal = await dataManager.createRelativeJournal({
      title: 'Indicator origin',
      dayOffset: 0,
    });
    const dueJournal = await dataManager.createFutureJournal({
      title: 'Indicator deadline',
      daysAhead: 2,
    });
    // **Two** tasks, not one. The indicator is a count rather than a flag, and
    // one task cannot tell the two apart: `1 due` is what a boolean rendered as
    // a number would say as well. Two is the smallest fixture that proves the
    // number is counted, and it is also what exercises the plural wording on
    // the real listing path.
    await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text: taskText('Confirm the booking'),
    });
    await dataManager.createTask({
      creatingJournalId: creatingJournal.id,
      dueJournalId: dueJournal.id,
      text: taskText('Pack the projector'),
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Both fixtures sit inside the list's initial today ± 3 day window, so the
    // only movement needed is bringing each row into view.
    const dueHeading = page.getByRole('heading', { name: dueJournal.title });
    await dueHeading.scrollIntoViewIfNeeded();
    const badge = dueHeading.getByTestId('tasks-due-badge');
    await expect(badge).toBeVisible();

    // The short form is for the eye; the full phrase is for the ear. Both are
    // matched whole rather than as substrings, because "2 due" is a substring
    // of "12 due" and a count that had gone wrong by an order of magnitude
    // would otherwise still satisfy the assertion.
    await expect(badge.locator('span[aria-hidden="true"]')).toHaveText('2 due');
    await expect(badge.locator('.sr-only')).toHaveText(
      '2 tasks due in this journal'
    );

    // The journal a task was merely *created* in has nothing due in it, and the
    // indicator must not claim otherwise.
    const creatingHeading = page.getByRole('heading', {
      name: creatingJournal.title,
    });
    await creatingHeading.scrollIntoViewIfNeeded();
    await expect(creatingHeading).toBeVisible();
    await expect(creatingHeading.getByTestId('tasks-due-badge')).toHaveCount(0);
  });
});

/**
 * A task on a list — one with no journal at all — on a journal's page.
 *
 * Created for real on a list, so it has neither anchor. The one write that
 * puts such a task on a journal's page is a mention, so it is linked to the
 * journal as an intermediate journal and listed under **Mentioned**.
 */
test.describe('Journal Task Surface — a task with no due journal', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('shows a task on a list mentioned here without erroring, and offers it no retarget', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const journal = await dataManager.createFutureJournal({
      title: 'Beach weekend',
      daysAhead: 2,
    });
    const journalOnlyText = taskText('Book the campsite');
    const journalOnly = await dataManager.createTask({
      creatingJournalId: journal.id,
      dueJournalId: journal.id,
      text: journalOnlyText,
    });

    const list = await dataManager.createTaskList(taskText('Beach packing'));
    const listTaskText = taskText('Buy sunscreen');
    const listTask = await dataManager.createListTask({
      taskListId: list.id,
      text: listTaskText,
    });
    await dataManager.attachTaskMention(listTask.id, journal.id);

    const pageErrors: Error[] = [];
    page.on('pageerror', error => pageErrors.push(error));

    await openJournal(page, journal);

    const mentionedGroup = page.getByTestId('journal-tasks-group-mentioned');
    const listRow = mentionedGroup.getByTestId(`journal-task-${listTask.id}`);
    await expect(listRow.getByTestId('journal-task-text')).toHaveText(
      listTaskText
    );
    // Nothing about a due journal it does not have, and never lapsed.
    await expect(listRow.getByText(/Due in/)).toHaveCount(0);
    await expect(listRow.getByTestId('journal-task-lapsed')).toHaveCount(0);

    // Its status actions stay; with no due journal to move from, it is not
    // offered a reschedule here — it is given one through the task’s own edit.
    const listActions = listRow.getByRole('group', { name: 'Task actions' });
    await expect(
      listActions.getByRole('button', { name: 'Mark done' })
    ).toBeVisible();
    await expect(
      listActions.getByTestId('journal-task-action-retarget')
    ).toHaveCount(0);

    // The journal-only task beside it is exactly as before.
    const dueRow = page
      .getByTestId('journal-tasks-group-due')
      .getByTestId(`journal-task-${journalOnly.id}`);
    await expect(dueRow.getByTestId('journal-task-text')).toHaveText(
      journalOnlyText
    );
    await expect(
      dueRow.getByTestId('journal-task-action-retarget')
    ).toBeVisible();

    await expectFitsPhoneWithoutErrors(page, pageErrors);
  });
});

/**
 * A task on a list that is **due** in this journal.
 *
 * The first real task to reach a journal's *Due* group with no creating
 * journal. A list task never lapses, and its due journal is a plain date, so
 * the row offers a reschedule that keeps its status — never a resurrect or a
 * reopen — beside its direct status actions.
 */
test.describe('Journal Task Surface — a task on a list due here', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('shows a list task due here under Due, never lapsed, offers a keeps-status reschedule, and marks it done', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Two UTC days out, so it is in the future whatever the clock says.
    const journal = await dataManager.createFutureJournal({
      title: 'Beach weekend',
      daysAhead: 2,
    });
    const list = await dataManager.createTaskList(taskText('Beach packing'));
    const text = taskText('Pack the tent');
    const listTask = await dataManager.createListTask({
      taskListId: list.id,
      text,
      dueJournalId: journal.id,
    });
    expect(listTask.dueJournalId).toBe(journal.id);

    const pageErrors: Error[] = [];
    page.on('pageerror', error => pageErrors.push(error));

    await openJournal(page, journal);

    const row = page
      .getByTestId('journal-tasks-group-due')
      .getByTestId(`journal-task-${listTask.id}`);
    await expect(row.getByTestId('journal-task-text')).toHaveText(text);
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();
    await expect(row.getByTestId('journal-task-lapsed')).toHaveCount(0);

    const actions = row.getByRole('group', { name: 'Task actions' });
    await expect(
      actions.getByRole('button', {
        name: 'Reschedule task onto another due journal',
      })
    ).toBeVisible();

    // The row flips optimistically, so the write itself is awaited before the
    // reload: navigating away first could cut the PATCH off.
    const statusWrite = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/tasks/${listTask.id}`) &&
        response.request().method() === 'PATCH'
    );
    await actions.getByRole('button', { name: 'Mark done' }).click();
    expect((await statusWrite).ok()).toBe(true);
    await expect(row.getByText('Done', { exact: true })).toBeVisible();

    // The reload proves the change was written rather than merely drawn.
    await openJournal(page, journal);
    await expect(row.getByText('Done', { exact: true })).toBeVisible();
    await expect(
      actions.getByRole('button', { name: 'Return to not done' })
    ).toBeVisible();

    await expectFitsPhoneWithoutErrors(page, pageErrors);
  });
});

/**
 * A task on a list whose due journal has gone by.
 *
 * "On a journal page, a list task past its date shows the overdue marker and
 * direct actions, never the lapsed marker", and "a done or cancelled list task
 * can be set back to not done, without retargeting". The task is created due
 * in a future journal and the journal then moved into the past — the lapse
 * recipe above — because no write lets a task be made due in the past.
 */
test.describe('Journal Task Surface — an overdue task on a list', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('marks an overdue list task overdue, never lapsed, and reopens it directly after cancelling', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const list = await dataManager.createTaskList(taskText('Event prep'));
    const journal = await dataManager.createFutureJournal({
      // Short on purpose: the journal header does not wrap one long word, and
      // that is not what this test is about.
      title: 'Venue visit',
      daysAhead: 2,
    });
    const text = taskText('Book the venue');
    const listTask = await dataManager.createListTask({
      taskListId: list.id,
      text,
      dueJournalId: journal.id,
    });
    expect(listTask.dueJournalId).toBe(journal.id);

    const moved = await dataManager.moveJournalToPast(journal.id, 3);
    expect(moved.status()).toBe(200);
    // The marker names the due journal's day, which the backend resolves in
    // UTC for the e2e user — the same day `utcDayOffset` built it on.
    const dueDay = new Date(utcDayOffset(-3)).getUTCDate();

    const pageErrors: Error[] = [];
    page.on('pageerror', error => pageErrors.push(error));

    await openJournal(page, journal);

    const row = page
      .getByTestId('journal-tasks-group-due')
      .getByTestId(`journal-task-${listTask.id}`);
    await expect(row.getByTestId('journal-task-text')).toHaveText(text);
    const overdue = row.getByTestId('journal-task-overdue');
    await expect(overdue).toHaveText(
      new RegExp(`^Overdue · ${dueDay} [A-Z][a-z]{2,3}$`)
    );
    await expect(row.getByTestId('journal-task-lapsed')).toHaveCount(0);

    const actions = row.getByRole('group', { name: 'Task actions' });

    /** The PATCH a status button sends, awaited so its result is known. */
    const statusWrite = () =>
      page.waitForResponse(
        response =>
          response.url().endsWith(`/api/tasks/${listTask.id}`) &&
          response.request().method() === 'PATCH'
      );

    const cancelWrite = statusWrite();
    await actions.getByRole('button', { name: 'Cancel task' }).click();
    expect((await cancelWrite).ok()).toBe(true);
    await expect(row.getByText('Cancelled', { exact: true })).toBeVisible();
    await expect(overdue).toHaveCount(0);

    // Reopened by its status. A new due journal would keep it cancelled: a
    // list task's reschedule is a plain date change, still offered here.
    const reopen = actions.getByRole('button', { name: 'Return to not done' });
    await expect(reopen).toBeVisible();
    await expect(
      actions.getByRole('button', { name: 'Mark done' })
    ).toBeVisible();
    await expect(
      actions.getByRole('button', {
        name: 'Reschedule task onto another due journal',
      })
    ).toBeVisible();
    // A control this phase adds, held to the phone touch-target minimum.
    const reopenBox = await reopen.boundingBox();
    expect(reopenBox?.height).toBeGreaterThanOrEqual(44);
    expect(reopenBox?.width).toBeGreaterThanOrEqual(44);

    const reopenWrite = statusWrite();
    await reopen.click();
    expect((await reopenWrite).ok()).toBe(true);
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();

    // The reload proves the reopen was written, and the server — the only
    // judge of the day boundary — reports the reopened task overdue again.
    await openJournal(page, journal);
    await expect(row.getByText('Not done', { exact: true })).toBeVisible();
    await expect(overdue).toHaveText(
      new RegExp(`^Overdue · ${dueDay} [A-Z][a-z]{2,3}$`)
    );
    await expect(row.getByTestId('journal-task-lapsed')).toHaveCount(0);

    await expectFitsPhoneWithoutErrors(page, pageErrors);
  });

  test('reschedules a done list task to another journal, and it stays done', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const fromJournal = await dataManager.createFutureJournal({
      title: taskText('Beach weekend'),
      daysAhead: 2,
    });
    const toJournal = await dataManager.createFutureJournal({
      title: taskText('Long weekend'),
      daysAhead: 5,
    });
    const list = await dataManager.createTaskList(taskText('Beach packing'));
    const text = taskText('Pack the tent');
    const listTask = await dataManager.createListTask({
      taskListId: list.id,
      text,
      dueJournalId: fromJournal.id,
    });
    await dataManager.setTaskStatus(listTask.id, 'done');

    const pageErrors: Error[] = [];
    page.on('pageerror', error => pageErrors.push(error));

    await openJournal(page, fromJournal);

    const dueRow = page
      .getByTestId('journal-tasks-group-due')
      .getByTestId(`journal-task-${listTask.id}`);
    await expect(dueRow.getByText('Done', { exact: true })).toBeVisible();

    const trigger = dueRow.getByRole('button', {
      name: 'Reschedule task onto another due journal',
    });
    // The trigger is the row's shared size='sm' action button, which this
    // change reuses rather than adds; its 32px height is a known gap shared by
    // every row action, recorded in the iteration doc rather than asserted.
    await trigger.click();

    const dialog = page.getByRole('dialog', {
      name: 'Move this task to another journal',
    });
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAccessibleDescription(/keeps its status/i);
    await expect(dialog.getByTestId('retarget-task-text')).toHaveText(text);

    const retargetWrite = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/tasks/${listTask.id}/retarget`) &&
        response.request().method() === 'POST'
    );
    await chooseDueJournal(dialog, toJournal);
    await submitRetarget(dialog);
    expect((await retargetWrite).ok()).toBe(true);

    // No reopen confirmation: a list task's date never reopens it, so the
    // dialog closes on the first submit without asking.
    await expect(page.getByTestId('retarget-reopen-confirm')).toHaveCount(0);
    await expect(dialog).toBeHidden();

    // Gone from Due here, and kept as a mention — still done.
    await expect(
      page
        .getByTestId('journal-tasks-group-due')
        .getByTestId(`journal-task-${listTask.id}`)
    ).toHaveCount(0);
    const mentionedRow = page
      .getByTestId('journal-tasks-group-mentioned')
      .getByTestId(`journal-task-${listTask.id}`);
    await expect(mentionedRow.getByTestId('journal-task-text')).toHaveText(
      text
    );
    await expect(mentionedRow.getByText('Done', { exact: true })).toBeVisible();

    // And due in the journal it moved to, done.
    await openJournal(page, toJournal);
    const movedRow = page
      .getByTestId('journal-tasks-group-due')
      .getByTestId(`journal-task-${listTask.id}`);
    await expect(movedRow.getByTestId('journal-task-text')).toHaveText(text);
    await expect(movedRow.getByText('Done', { exact: true })).toBeVisible();

    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth
        )
      )
      .toBe(true);
    expect(pageErrors).toEqual([]);
  });
});

// A guard on the fixtures rather than on the product: every date in this file
// comes from `utcDayOffset`, and the specs above only mean what they say while
// it really is anchored to UTC days.
/**
 * The journal delete confirmation and tasks on a list.
 *
 * A task on a list never blocks a journal's deletion: it loses its link to the
 * journal instead, and the confirmation says how many will. The count comes
 * from `GET /api/journals/{id}/delete-preview`, read when the dialog opens.
 *
 * **No list task can exist yet.** Nothing on REST or MCP puts a task on a
 * list until ITER21-001 Phase 19, so the real backend can only answer zero.
 * The first test makes that real round trip, proving the route and its wire
 * shape. The second stands a typed stub in for the preview to see the count
 * rendered. Replace the stub with a real list task once Phase 19 lands.
 */
test.describe('Journal delete confirmation and list tasks', () => {
  /** A phone-width viewport, for the no-horizontal-scroll check. */
  const MOBILE = { width: 390, height: 844 };

  test('deletes a journal no list task links to, without a list-task warning', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => await dataManager.cleanup());

    const journal = await dataManager.createRelativeJournal({
      title: taskText('Nothing on a list links here'),
      dayOffset: 0,
    });

    await openJournal(page, journal);

    const previewResponse = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/journals/${journal.id}/delete-preview`) &&
        response.request().method() === 'GET'
    );
    await page.getByTestId('delete-journal-button').click();
    const dialog = page.getByRole('alertdialog', {
      name: 'Delete this journal?',
    });
    await expect(dialog).toBeVisible();

    const preview = await previewResponse;
    expect(preview.status()).toBe(200);
    const body = (await preview.json()) as JournalDeletePreviewResponse;
    expect(body.data.type).toBe('journal-delete-previews');
    expect(body.data.attributes.list_tasks_losing_link).toBe(0);

    const confirm = dialog.getByTestId('confirm-delete-journal');
    await expect(confirm).toBeEnabled();
    await expect(dialog.getByTestId('delete-journal-list-tasks')).toHaveCount(
      0
    );

    const deleteResponse = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/journals/${journal.id}`) &&
        response.request().method() === 'DELETE'
    );
    await confirm.click();
    expect((await deleteResponse).status()).toBe(204);
    await expect(page).toHaveURL(/\/journals$/);
  });

  test('states how many list tasks will lose their link', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const journal = await dataManager.createRelativeJournal({
      title: taskText('Two list tasks link here'),
      dayOffset: 0,
    });

    // Two real tasks on a list, each linked here only as a mention: the delete
    // unlinks them rather than being blocked by them.
    const list = await dataManager.createTaskList(taskText('Trip prep'));
    const listTasks = await Promise.all(
      [taskText('Buy maps'), taskText('Charge the radio')].map(text =>
        dataManager.createListTask({ taskListId: list.id, text })
      )
    );
    for (const listTask of listTasks) {
      await dataManager.attachTaskMention(listTask.id, journal.id);
    }

    await page.setViewportSize(MOBILE);
    await openJournal(page, journal);
    await page.getByTestId('delete-journal-button').click();
    const dialog = page.getByRole('alertdialog', {
      name: 'Delete this journal?',
    });
    await expect(dialog).toBeVisible();

    const count = dialog.getByTestId('delete-journal-list-tasks');
    await expect(count).toHaveText(
      '2 tasks on a list link to this journal and will lose that link. Any due here will have no due date.'
    );
    // It arrives after the dialog opens, so it lands in the dialog's live
    // region (announced on arrival) inside its description.
    await expect(dialog.getByRole('status')).toContainText(
      '2 tasks on a list link to this journal'
    );
    await expect(dialog).toHaveAccessibleDescription(
      /2 tasks on a list link to this journal/
    );
    await expect(dialog.getByTestId('confirm-delete-journal')).toBeEnabled();

    // Nothing the dialog adds may push a phone into scrolling sideways.
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    const dialogOverflow = await dialog.evaluate(element => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }));
    expect(dialogOverflow.scrollWidth).toBeLessThanOrEqual(
      dialogOverflow.clientWidth
    );

    // Declining keeps the journal: the count informs, it deletes nothing.
    await dialog.getByRole('button', { name: 'Keep journal' }).click();
    await expect(dialog).toBeHidden();
    const kept = await page.request.get(`/api/journals/${journal.id}`);
    expect(kept.status()).toBe(200);

    // Deleting for real unlinks both tasks and keeps them on their list.
    await page.getByTestId('delete-journal-button').click();
    await expect(dialog).toBeVisible();
    await expect(count).toBeVisible();
    const deleteResponse = page.waitForResponse(
      response =>
        response.url().endsWith(`/api/journals/${journal.id}`) &&
        response.request().method() === 'DELETE'
    );
    await dialog.getByTestId('confirm-delete-journal').click();
    expect((await deleteResponse).status()).toBe(204);
    await expect(page).toHaveURL(/\/journals$/);

    for (const listTask of listTasks) {
      const read = await page.request.get(`/api/tasks/${listTask.id}`);
      expect(read.status()).toBe(200);
      const body = (await read.json()) as TaskReadResponse & {
        // Carried by every task response; not yet on the web app's type.
        data: { attributes: { task_list_id: number | null } };
      };
      expect(body.data.attributes.intermediate_journal_ids).toEqual([]);
      expect(body.data.attributes.task_list_id).toBe(Number(list.id));
    }
  });
});

test.describe('Task fixture dates', () => {
  test('are whole UTC days from today, not local wall-clock times', async () => {
    const today = new Date(utcDayOffset(0));
    const ahead = new Date(utcDayOffset(2));
    const behind = new Date(utcDayOffset(-2));

    expect(utcDayOffset(0)).toMatch(/T12:00:00\.000Z$/);
    expect(ahead.getTime() - today.getTime()).toBe(2 * 24 * 60 * 60 * 1000);
    expect(today.getTime() - behind.getTime()).toBe(2 * 24 * 60 * 60 * 1000);
    expect(new Date(utcDayOffset(0, 13)).getUTCHours()).toBe(13);
  });
});
