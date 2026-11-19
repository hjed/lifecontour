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

/** The switch button for one type in the open dialog. */
export function newTypeButton(dialog: Locator, label: string): Locator {
  return dialog
    .getByRole('group', { name: 'What to create' })
    .getByRole('button', { name: label });
}

/** Switch the open dialog to a type and wait until it is the selected one. */
export async function selectNewType(
  dialog: Locator,
  label: string
): Promise<void> {
  const type = newTypeButton(dialog, label);
  await type.click();
  await expect(type).toHaveAttribute('aria-pressed', 'true');
}

/**
 * Fill the Journal panel's title, create it, and return the new journal's id
 * taken from the create response.
 */
export async function createJournalFromDialog(
  page: Page,
  dialog: Locator,
  title: string
): Promise<string> {
  const panel = dialog.getByRole('region', { name: 'Journal' });
  await panel.getByLabel('Title', { exact: true }).fill(title);
  const created = page.waitForResponse(
    response =>
      new URL(response.url()).pathname === '/api/journals' &&
      response.request().method() === 'POST'
  );
  await panel.getByRole('button', { name: 'Create Journal' }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const body = (await response.json()) as { data: { id: string | number } };
  return String(body.data.id);
}

/** A journal a test created, as its data manager reports it. */
interface DialogJournal {
  readonly id: string | number;
  readonly title: string;
}

/** The New dialog's Task panel. */
export function taskPanel(dialog: Locator): Locator {
  return dialog.getByRole('region', { name: 'Task' });
}

/** The Task panel's creating-journal search. */
export function creatingJournalField(dialog: Locator): Locator {
  return taskPanel(dialog).getByRole('combobox', {
    name: 'Journal this task arose in',
  });
}

/**
 * Choose the creating journal in the Task panel's search.
 *
 * The whole fill-then-click sequence is retried, with short inner timeouts,
 * for the reason `chooseDueJournal` gives: on a phone a touch-blur can close
 * the result list between the two steps. Every step is idempotent.
 */
export async function chooseCreatingJournal(
  dialog: Locator,
  journal: DialogJournal
): Promise<void> {
  const search = creatingJournalField(dialog);
  // A substring match: the option's name is the title followed by its date.
  const option = taskPanel(dialog)
    .getByRole('option')
    .filter({ hasText: journal.title });

  await expect(async () => {
    await search.fill('', { timeout: 5000 });
    await search.fill(journal.title, { timeout: 5000 });
    await expect(option).toBeVisible({ timeout: 5000 });
    await option.getByRole('button').click({ timeout: 5000 });
    await expect(search).toHaveValue(journal.title, { timeout: 5000 });
  }).toPass({ timeout: 45000 });
}

/**
 * Create the task the Task panel holds and return the creating journal id the
 * request went to, taken from its path.
 *
 * The click is level-triggered, as `submitRetarget`'s is: the due picker's
 * list settles under the footer and can swallow a click. It only repeats while
 * the dialog is still open with its submit enabled, so a click that landed is
 * never followed by another.
 */
export async function submitTaskFromDialog(
  page: Page,
  dialog: Locator
): Promise<string> {
  const submit = taskPanel(dialog).getByTestId('create-task-dialog-submit');
  const created = page.waitForResponse(
    response =>
      /^\/api\/journals\/\d+\/tasks$/.test(new URL(response.url()).pathname) &&
      response.request().method() === 'POST'
  );

  await expect(async () => {
    if ((await dialog.isVisible()) && (await submit.isEnabled())) {
      await submit.click({ timeout: 2000 });
    }
    await expect(dialog).toBeHidden({ timeout: 3000 });
  }).toPass({ timeout: 30000 });

  const response = await created;
  expect(response.status()).toBe(201);
  const [, , , journalId] = new URL(response.url()).pathname.split('/');
  return journalId;
}
