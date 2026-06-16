import { test, expect } from './fixtures';
import type { Locator, Page } from '@playwright/test';

/**
 * Browser E2E for the ITER13-003 web contact-merge flow (Phases 2 & 3).
 *
 * Covers the two required paths from the iteration doc:
 *   1. Full conflict-resolution merge (survivor / source / custom per field).
 *   2. No-conflict direct merge (resolution dialog skips straight to confirm).
 *
 * Each test creates its own deterministic data via the contacts REST API and
 * cleans it up afterwards. The contact search combobox is MeiliSearch-backed
 * (async indexing), so the fill+select sequence is wrapped in `toPass` to retry
 * until the freshly-created source is indexed and selectable.
 */

interface RawContact {
  id: string;
  firstName: string;
  lastName: string;
}

/** Create a contact via the REST API with exact field values (no uniquifying). */
async function createContact(
  page: Page,
  attrs: { firstName: string; lastName: string; nickName?: string }
): Promise<RawContact> {
  const response = await page.request.post('/api/contacts', {
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify({
      data: {
        type: 'contacts',
        attributes: {
          first_name: attrs.firstName,
          last_name: attrs.lastName,
          ...(attrs.nickName ? { nick_name: attrs.nickName } : {}),
          is_favourite: false,
        },
      },
    }),
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return {
    id: body.data.id,
    firstName: attrs.firstName,
    lastName: attrs.lastName,
  };
}

async function deleteContactQuietly(page: Page, id: string): Promise<void> {
  // The source is removed by the merge; a follow-up delete may 404 — ignore it.
  await page.request.delete(`/api/contacts/${id}`).catch(() => undefined);
}

/**
 * Fill the merge dialog's combobox and click the matching source option.
 * Wrapped by the caller in `expect(...).toPass()` so the whole sequence retries
 * while MeiliSearch indexes the new contact (and to absorb debounce/blur races).
 */
async function selectSourceInCombobox(dialog: Locator, query: string) {
  const combobox = dialog.getByRole('combobox');
  await combobox.clear();
  await combobox.fill(query);

  const option = dialog.locator('li[role="option"]').first();
  await expect(option).toBeVisible({ timeout: 15000 });
  await option.click();
}

/**
 * The contacts search endpoint is MeiliSearch-backed with async indexing, so a
 * freshly-created contact is not immediately findable. Poll the API until the
 * target contact appears before driving the (search-backed) combobox.
 */
async function waitUntilSearchable(page: Page, query: string, id: string) {
  await expect
    .poll(
      async () => {
        const res = await page.request.get(
          `/api/search/contacts?q=${encodeURIComponent(query)}&limit=20`
        );
        if (!res.ok()) return false;
        const body = await res.json();
        return (body.data ?? []).some((c: { id: string }) => c.id === id);
      },
      { timeout: 30000, intervals: [500, 1000, 2000] }
    )
    .toBe(true);
}

/**
 * Open the merge dialog from the detail page action area.
 *
 * The action button sits high on the page; Playwright scrolls it to the top to
 * click, where the `z-50` sticky app header overlaps it. A real user taps the
 * (visible) button fine — so activate it via the keyboard to avoid the
 * sticky-header hit-test artifact while still exercising keyboard operability.
 */
async function openMergeDialog(page: Page): Promise<Locator> {
  const mergeButton = page.getByRole('button', { name: /merge contact/i });
  await expect(mergeButton).toBeVisible();
  await mergeButton.focus();
  await mergeButton.press('Enter');

  const dialog = page
    .getByRole('dialog')
    .filter({ hasText: /Merge Another Contact/i });
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe('Contact Merge Workflow (web UI)', () => {
  test('resolves field conflicts then merges, deleting the source', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    // Short unique token: timestamp + random so names can't collide across
    // parallel/same-millisecond runs, while staying compact (long names overflow
    // the identity row and can push the action buttons under the sticky header).
    const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

    const survivor = await createContact(page, {
      firstName: `Survivor${suffix}`,
      lastName: 'Keeper',
    });
    const source = await createContact(page, {
      firstName: `Source${suffix}`,
      lastName: 'Absorbed',
    });

    testCleanup(async () => {
      await deleteContactQuietly(page, survivor.id);
      await deleteContactQuietly(page, source.id);
    });

    await waitUntilSearchable(page, `Source${suffix}`, source.id);

    await page.goto(`/contacts/${survivor.id}`);
    await expect(page.getByTestId('first-name-field')).toContainText(
      `Survivor${suffix}`
    );

    const dialog = await openMergeDialog(page);

    // Retry the combobox fill+select to absorb debounce/blur races.
    await expect(async () => {
      await selectSourceInCombobox(dialog, `Source${suffix}`);
      await expect(dialog.getByText(/Selected to merge:/i)).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    // The search results dropdown is absolutely positioned over the footer;
    // wait for it to close after selection so it can't intercept the Next click.
    await expect(dialog.locator('li[role="option"]')).toHaveCount(0);
    await dialog.getByRole('button', { name: /next/i }).click();

    const resolution = page
      .getByRole('dialog')
      .filter({ hasText: 'Resolve Merge Conflicts' });
    await expect(resolution).toBeVisible();

    // first_name: take the source value.
    await resolution.getByTestId('radio-source-first_name').click();
    // last_name: type a custom value.
    await resolution.getByTestId('radio-custom-last_name').click();
    const customLastName = resolution.getByPlaceholder(
      /enter custom last name/i
    );
    await customLastName.fill('MergedSurname');

    const mergeResponsePromise = page.waitForResponse(
      response =>
        response.url().includes(`/api/contacts/${survivor.id}/merge`) &&
        response.request().method() === 'POST'
    );

    await resolution
      .getByRole('button', { name: /resolve and merge/i })
      .click();
    const mergeResponse = await mergeResponsePromise;
    expect(mergeResponse.status()).toBe(200);

    await expect(resolution).toBeHidden();

    // Survivor now reflects the resolved values.
    await expect(page.getByTestId('first-name-field')).toContainText(
      `Source${suffix}`
    );
    await expect(page.getByTestId('last-name-field')).toContainText(
      'MergedSurname'
    );

    // The source contact no longer exists.
    const sourceGet = await page.request.get(`/api/contacts/${source.id}`);
    expect(sourceGet.status()).toBe(404);
  });

  test('merges directly when there are no conflicts', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    // Short unique token: timestamp + random so names can't collide across
    // parallel/same-millisecond runs, while staying compact (long names overflow
    // the identity row and can push the action buttons under the sticky header).
    const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

    // Identical surfaced fields → no conflicts. The combobox excludes the
    // current (survivor) contact, so only the source matches the shared name.
    const survivor = await createContact(page, {
      firstName: `Twin${suffix}`,
      lastName: `Same${suffix}`,
    });
    const source = await createContact(page, {
      firstName: `Twin${suffix}`,
      lastName: `Same${suffix}`,
    });

    testCleanup(async () => {
      await deleteContactQuietly(page, survivor.id);
      await deleteContactQuietly(page, source.id);
    });

    await waitUntilSearchable(page, `Twin${suffix}`, source.id);

    await page.goto(`/contacts/${survivor.id}`);
    await expect(page.getByTestId('first-name-field')).toContainText(
      `Twin${suffix}`
    );

    const dialog = await openMergeDialog(page);

    await expect(async () => {
      await selectSourceInCombobox(dialog, `Twin${suffix}`);
      await expect(dialog.getByText(/Selected to merge:/i)).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    // The search results dropdown is absolutely positioned over the footer;
    // wait for it to close after selection so it can't intercept the Next click.
    await expect(dialog.locator('li[role="option"]')).toHaveCount(0);
    await dialog.getByRole('button', { name: /next/i }).click();

    // No conflicts → the resolution dialog shows the confirm state directly.
    const confirm = page
      .getByRole('dialog')
      .filter({ hasText: /No conflicts detected/i });
    await expect(confirm).toBeVisible();

    const mergeResponsePromise = page.waitForResponse(
      response =>
        response.url().includes(`/api/contacts/${survivor.id}/merge`) &&
        response.request().method() === 'POST'
    );

    await confirm.getByRole('button', { name: /^merge$/i }).click();
    const mergeResponse = await mergeResponsePromise;
    expect(mergeResponse.status()).toBe(200);

    await expect(confirm).toBeHidden();

    // Survivor remains; source is gone.
    await expect(page.getByTestId('first-name-field')).toContainText(
      `Twin${suffix}`
    );
    const sourceGet = await page.request.get(`/api/contacts/${source.id}`);
    expect(sourceGet.status()).toBe(404);
  });
});
