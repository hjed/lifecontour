import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import type { TestJournal } from './fixtures';
import {
  chooseCreatingJournal,
  createContactFromDialog,
  createJournalFromDialog,
  creatingJournalField,
  newButton,
  newTypeButton,
  openNewDialog,
  selectNewType,
  submitTaskFromDialog,
  taskPanel,
} from './utils/new-dialog';
import { chooseDueJournal } from './utils/retarget-dialog';
import {
  expectNoHorizontalScroll,
  expectTouchTarget,
} from './utils/phone-layout';

/** The opened contact's first name, shown as its inline-edit control. */
function contactFirstName(page: Page) {
  return page
    .getByRole('region', { name: 'Contact Detail' })
    .getByRole('button', { name: 'First name' });
}

/** The opened journal's title, shown as its inline-edit field. */
function journalTitle(page: Page) {
  return page.getByTestId('journal-title-field');
}

function uniqueName(prefix: string): string {
  return `${prefix}${crypto.randomUUID().slice(0, 8)}`;
}

/**
 * Open a journal and wait for its tasks card: it renders nothing while the
 * listing is in flight, so its presence means the journal's tasks have loaded.
 */
async function openJournal(page: Page, journal: TestJournal): Promise<Locator> {
  await page.goto(`/journals/${journal.id}`);
  const section = page.getByTestId('journal-tasks-section');
  await expect(section).toBeVisible();
  return section;
}

/** The text of the tasks a journal shows as created in it. */
function createdHere(page: Page): Locator {
  return page
    .getByTestId('journal-tasks-group-created')
    .getByTestId('journal-task-text');
}

/** Two journals for a task: today's, where it arises, and a future one. */
async function taskJournals(dataManager: TestDataManager) {
  const creating = await dataManager.createRelativeJournal({
    title: uniqueName('Newdialog arose '),
    dayOffset: 0,
  });
  const due = await dataManager.createFutureJournal({
    title: uniqueName('Newdialog due '),
    daysAhead: 2,
  });
  return { creating, due };
}

test.describe('New dialog — desktop', () => {
  test('offers New in the top bar on authenticated pages', async ({
    authenticatedPage: page,
    isMobile,
  }) => {
    if (isMobile) test.skip();

    for (const path of ['/', '/contacts', '/journals']) {
      await page.goto(path);
      await expect(newButton(page)).toBeVisible();
      await expect(newButton(page)).toHaveAttribute('aria-haspopup', 'dialog');
    }
  });

  test('creates a contact from New', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const firstName = uniqueName('Newdialog');

    await page.goto('/journals');
    const dialog = await openNewDialog(page);
    await selectNewType(dialog, 'Contact');

    const contactId = await createContactFromDialog(page, dialog, firstName);
    dataManager.trackContact(contactId);

    await expect(page).toHaveURL(new RegExp(`/contacts/${contactId}$`));
    await expect(contactFirstName(page)).toHaveText(firstName);
    await expect(dialog).toBeHidden();
  });

  test('creates a journal from New', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const title = uniqueName('Newdialog journal ');

    await page.goto('/contacts');
    const dialog = await openNewDialog(page);
    // Task is the first type, so every opening starts on it.
    await expect(newTypeButton(dialog, 'Task')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await selectNewType(dialog, 'Journal');

    const journalId = await createJournalFromDialog(page, dialog, title);
    dataManager.trackJournal(journalId);

    await expect(page).toHaveURL(new RegExp(`/journals/${journalId}$`));
    await expect(journalTitle(page)).toContainText(title);
    await expect(dialog).toBeHidden();
  });

  test('creates a task in the journal being viewed from New', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const { creating, due } = await taskJournals(dataManager);
    const text = uniqueName('Print the permit ');

    await openJournal(page, creating);
    const dialog = await openNewDialog(page);

    // New opens on Task, ready to type, with the journal being viewed as the
    // place the task arose.
    await expect(newTypeButton(dialog, 'Task')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    const panel = taskPanel(dialog);
    await expect(panel.getByTestId('create-task-text')).toBeFocused();
    await expect(creatingJournalField(dialog)).toHaveValue(creating.title);

    await panel.getByTestId('create-task-text').fill(text);
    await chooseDueJournal(panel, due);
    const journalId = await submitTaskFromDialog(page, dialog);

    expect(journalId).toBe(String(creating.id));
    // Quick capture: the user stays where they were, and the page they are on
    // shows the new task.
    await expect(page).toHaveURL(new RegExp(`/journals/${creating.id}$`));
    await expect(createdHere(page)).toHaveText(text);
  });

  test('creates a task in a journal chosen from New', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const { creating, due } = await taskJournals(dataManager);
    const text = uniqueName('Book the hut ');

    await page.goto('/contacts');
    const dialog = await openNewDialog(page);
    const panel = taskPanel(dialog);

    // Away from a journal there is nothing to pre-fill, and nothing is sent
    // until the user chooses.
    await expect(creatingJournalField(dialog)).toHaveValue('');
    await panel.getByTestId('create-task-text').fill(text);
    await chooseDueJournal(panel, due);
    await panel.getByTestId('create-task-dialog-submit').click();
    await expect(
      panel.getByText('Choose the journal this task arose in.')
    ).toBeVisible();
    await expect(creatingJournalField(dialog)).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    // Focus moves to the field, so its message is announced.
    await expect(creatingJournalField(dialog)).toBeFocused();

    // Escape in the open search closes its results, not the dialog and the
    // draft with it.
    await creatingJournalField(dialog).fill(creating.title);
    await expect(creatingJournalField(dialog)).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    await page.keyboard.press('Escape');
    await expect(creatingJournalField(dialog)).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    await expect(dialog).toBeVisible();
    await expect(panel.getByTestId('create-task-text')).toHaveValue(text);

    await chooseCreatingJournal(dialog, creating);
    const journalId = await submitTaskFromDialog(page, dialog);

    expect(journalId).toBe(String(creating.id));
    await expect(page).toHaveURL(/\/contacts$/);
    await openJournal(page, creating);
    await expect(createdHere(page)).toHaveText(text);
  });

  test('closes from Cancel and Escape without navigating', async ({
    authenticatedPage: page,
    isMobile,
  }) => {
    if (isMobile) test.skip();

    await page.goto('/journals');
    let dialog = await openNewDialog(page);
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(/\/journals$/);

    dialog = await openNewDialog(page);
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(newButton(page)).toBeFocused();
  });
});

test.describe('New dialog — phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('opens as a top sheet with no horizontal scroll and 44px targets', async ({
    authenticatedPage: page,
    isMobile,
  }) => {
    if (!isMobile) test.skip();

    await page.goto('/contacts');
    await expectNoHorizontalScroll(page);

    // Measured before opening: the open modal hides the rest of the page
    // from the accessibility tree.
    await expectTouchTarget(newButton(page), { retry: true });
    const dialog = await openNewDialog(page);

    // The sheet is pinned to the top edge and spans the viewport.
    await expect(async () => {
      const box = await dialog.boundingBox();
      expect(box).not.toBeNull();
      expect(Math.round(box!.y)).toBe(0);
      expect(Math.round(box!.width)).toBe(390);
    }).toPass();
    await expectNoHorizontalScroll(page);

    await expectTouchTarget(newTypeButton(dialog, 'Task'), { retry: true });
    await expectTouchTarget(newTypeButton(dialog, 'Journal'), { retry: true });
    await expectTouchTarget(newTypeButton(dialog, 'Contact'), { retry: true });
    await expectTouchTarget(dialog.getByRole('button', { name: 'Close' }), {
      retry: true,
    });
  });

  test('creates a contact from the New sheet', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (!isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const firstName = uniqueName('Newsheet');

    await page.goto('/contacts');
    const dialog = await openNewDialog(page);
    await selectNewType(dialog, 'Contact');
    const contactId = await createContactFromDialog(page, dialog, firstName);
    dataManager.trackContact(contactId);

    await expect(page).toHaveURL(new RegExp(`/contacts/${contactId}$`));
    await expect(contactFirstName(page)).toHaveText(firstName);
    await expect(dialog).toBeHidden();
  });

  test('creates a journal from the New sheet', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (!isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const title = uniqueName('Newsheet journal ');

    await page.goto('/journals');
    const dialog = await openNewDialog(page);
    await selectNewType(dialog, 'Journal');
    // The whole journal form fits the 390px sheet without sideways scroll.
    await expectNoHorizontalScroll(page);
    await expect(async () => {
      const box = await dialog.boundingBox();
      expect(box).not.toBeNull();
      expect(Math.round(box!.width)).toBe(390);
    }).toPass();
    // The sheet scrolls itself, so overflow inside it never widens the page.
    expect(
      await dialog.evaluate(sheet => sheet.scrollWidth <= sheet.clientWidth)
    ).toBe(true);

    const journalId = await createJournalFromDialog(page, dialog, title);
    dataManager.trackJournal(journalId);

    await expect(page).toHaveURL(new RegExp(`/journals/${journalId}$`));
    await expect(journalTitle(page)).toContainText(title);
    await expect(dialog).toBeHidden();
  });

  test('creates a task in a journal from the New sheet', async ({
    authenticatedPage: page,
    isMobile,
    testCleanup,
  }) => {
    if (!isMobile) test.skip();
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const { creating, due } = await taskJournals(dataManager);
    const text = uniqueName('Pack the stove ');

    await page.goto('/journals');
    const dialog = await openNewDialog(page);
    const panel = taskPanel(dialog);
    await expect(newTypeButton(dialog, 'Task')).toHaveAttribute(
      'aria-pressed',
      'true'
    );

    await panel.getByTestId('create-task-text').fill(text);
    await chooseCreatingJournal(dialog, creating);
    await chooseDueJournal(panel, due);

    // The task form fits the 390px sheet: nothing widens it sideways, and its
    // primary action is a full touch target.
    expect(
      await dialog.evaluate(sheet => sheet.scrollWidth <= sheet.clientWidth)
    ).toBe(true);
    await expectNoHorizontalScroll(page);
    await expectTouchTarget(panel.getByTestId('create-task-dialog-submit'), {
      retry: true,
    });

    const journalId = await submitTaskFromDialog(page, dialog);

    expect(journalId).toBe(String(creating.id));
    await openJournal(page, creating);
    await expect(createdHere(page)).toHaveText(text);
  });
});
