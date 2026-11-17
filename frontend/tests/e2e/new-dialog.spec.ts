import type { Locator, Page } from '@playwright/test';

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import {
  createContactFromDialog,
  newButton,
  openNewDialog,
} from './utils/new-dialog';

const MIN_TOUCH_TARGET = 44;

/** The opened contact's first name, shown as its inline-edit control. */
function contactFirstName(page: Page) {
  return page
    .getByRole('region', { name: 'Contact Detail' })
    .getByRole('button', { name: 'First name' });
}

async function expectTouchTarget(target: Locator) {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
  expect(box!.height).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
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
    await expect(
      dialog
        .getByRole('group', { name: 'What to create' })
        .getByRole('button', { name: 'Contact' })
    ).toHaveAttribute('aria-pressed', 'true');

    const contactId = await createContactFromDialog(page, dialog, firstName);
    dataManager.trackContact(contactId);

    await expect(page).toHaveURL(new RegExp(`/contacts/${contactId}$`));
    await expect(contactFirstName(page)).toHaveText(firstName);
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

    await expectTouchTarget(
      dialog
        .getByRole('group', { name: 'What to create' })
        .getByRole('button', { name: 'Contact' })
    );
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
    const contactId = await createContactFromDialog(page, dialog, firstName);
    dataManager.trackContact(contactId);

    await expect(page).toHaveURL(new RegExp(`/contacts/${contactId}$`));
    await expect(contactFirstName(page)).toHaveText(firstName);
    await expect(dialog).toBeHidden();
  });
});
