/**
 * Helpers for driving the top bar's New dialog in E2E tests.
 */

import { expect, type Locator, type Page } from '@playwright/test';

/** The New trigger in the top bar. */
export function newButton(page: Page): Locator {
  return page.getByRole('banner').getByRole('button', { name: 'New' });
}

/**
 * Open the New dialog and return it.
 *
 * Clicks only while the trigger reports `aria-expanded="false"`, so a retry
 * after a click that landed never toggles the dialog shut again.
 */
export async function openNewDialog(page: Page): Promise<Locator> {
  const trigger = newButton(page);
  const dialog = page.getByRole('dialog', { name: 'New' });
  await expect(trigger).toBeVisible();
  await expect(async () => {
    if ((await trigger.getAttribute('aria-expanded')) !== 'true') {
      await trigger.click({ timeout: 2_000 });
    }
    await expect(dialog).toBeVisible({ timeout: 2_000 });
  }).toPass();
  return dialog;
}

/**
 * Fill the Contact panel's first name, save, and return the new contact's id
 * taken from the create response.
 */
export async function createContactFromDialog(
  page: Page,
  dialog: Locator,
  firstName: string
): Promise<string> {
  await dialog.getByLabel(/first name/i).fill(firstName);
  const created = page.waitForResponse(
    response =>
      new URL(response.url()).pathname === '/api/contacts' &&
      response.request().method() === 'POST'
  );
  await dialog.getByRole('button', { name: /save contact/i }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const body = (await response.json()) as { data: { id: string | number } };
  return String(body.data.id);
}
