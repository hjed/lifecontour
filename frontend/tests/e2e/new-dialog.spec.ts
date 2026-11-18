import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import {
  createContactFromDialog,
  createJournalFromDialog,
  newButton,
  newTypeButton,
  openNewDialog,
  selectNewType,
} from './utils/new-dialog';

const MIN_TOUCH_TARGET = 44;

/** The opened contact's first name, shown as its inline-edit control. */
function contactFirstName(page: Page) {
  return page
    .getByRole('region', { name: 'Contact Detail' })
    .getByRole('button', { name: 'First name' });
}

/**
 * Assert a target is at least 44px each way. Retried, because the dialog
 * zooms in from 95% scale: a box read mid-animation comes up a fraction short.
 */
async function expectTouchTarget(target: Locator) {
  await expect(async () => {
    const box = await target.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
    expect(box!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
  }).toPass({ timeout: 5_000 });
}

/** The opened journal's title, shown as its inline-edit field. */
function journalTitle(page: Page) {
  return page.getByTestId('journal-title-field');
}

function uniqueName(prefix: string): string {
  return `${prefix}${crypto.randomUUID().slice(0, 8)}`;
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
    // Journal is the first type, so every opening starts on it.
    await expect(newTypeButton(dialog, 'Journal')).toHaveAttribute(
      'aria-pressed',
      'true'
    );

    const journalId = await createJournalFromDialog(page, dialog, title);
    dataManager.trackJournal(journalId);

    await expect(page).toHaveURL(new RegExp(`/journals/${journalId}$`));
    await expect(journalTitle(page)).toContainText(title);
    await expect(dialog).toBeHidden();
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
    const noHorizontalScroll = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      );
    expect(await noHorizontalScroll()).toBe(true);

    // Measured before opening: the open modal hides the rest of the page
    // from the accessibility tree.
    await expectTouchTarget(newButton(page));
    const dialog = await openNewDialog(page);

    // The sheet is pinned to the top edge and spans the viewport.
    await expect(async () => {
      const box = await dialog.boundingBox();
      expect(box).not.toBeNull();
      expect(Math.round(box!.y)).toBe(0);
      expect(Math.round(box!.width)).toBe(390);
    }).toPass();
    expect(await noHorizontalScroll()).toBe(true);

    await expectTouchTarget(newTypeButton(dialog, 'Journal'));
    await expectTouchTarget(newTypeButton(dialog, 'Contact'));
    await expectTouchTarget(dialog.getByRole('button', { name: 'Close' }));
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
    await expect(newTypeButton(dialog, 'Journal')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    // The whole journal form fits the 390px sheet without sideways scroll.
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth
      )
    ).toBe(true);
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
});
