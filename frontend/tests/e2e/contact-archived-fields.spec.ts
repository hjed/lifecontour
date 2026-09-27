/**
 * E2E tests for archived contact methods.
 *
 * Archiving and restoring go through the real field PATCH, the collapsed
 * "Archived" section and the asynchronously projected history feed. The
 * section's rendering details are unit-tested in ContactMethodsList.test.tsx
 * and ContactAddressesList.test.tsx; this covers the round trip they mock out.
 */

import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

function archivedFieldPatch(page: Page, contactId: string) {
  return page.waitForResponse(
    res =>
      res.url().includes(`/api/contacts/${contactId}/methods/`) &&
      res.url().endsWith('/fields/is_archived') &&
      res.request().method() === 'PATCH',
    { timeout: 15000 }
  );
}

test.describe('Archived contact methods', () => {
  test('archives a method into the collapsed section and restores it', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => {
      await data.cleanup();
    });
    const contact = await data.createContact({
      firstName: 'Archie',
      lastName: 'Fields',
    });
    const suffix = crypto.randomUUID().slice(0, 8);
    const current = `now-${suffix}@example.com`;
    const old = `then-${suffix}@example.com`;
    await data.addContactMethod(contact.id, {
      method_type: 'email',
      value: current,
      is_primary: true,
    });
    await data.addContactMethod(contact.id, {
      method_type: 'email',
      value: old,
    });

    await page.goto(`/contacts/${contact.id}`);
    const methods = page.getByTestId('contact-methods-list');
    await expect(methods.getByText(old)).toBeVisible();

    // Archive: the value leaves the list in use for the collapsed section.
    const archived = archivedFieldPatch(page, contact.id);
    await methods.getByRole('button', { name: `Archive ${old}` }).click();
    expect((await archived).status()).toBe(200);

    const trigger = methods.getByRole('button', {
      name: 'Archived contact methods (1)',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(methods.getByText(old)).toBeHidden();
    await expect(methods.getByText(current)).toBeVisible();

    await trigger.click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const archivedRegion = methods.getByRole('region', {
      name: 'Archived contact methods (1)',
    });
    await expect(archivedRegion.getByText(old)).toBeVisible();

    // History is projected asynchronously: poll until the archive lands.
    await expect(async () => {
      const response = await page.request.get(
        `/api/contacts/${contact.id}/history`
      );
      expect(response.ok()).toBeTruthy();
      const { data: entries } = await response.json();
      expect(
        entries.some(
          (e: { attributes: { field_name: string; new_value: string } }) =>
            e.attributes.field_name === 'is_archived' &&
            e.attributes.new_value === 'True'
        )
      ).toBe(true);
    }).toPass({ timeout: 30000 });

    // Restore: back in the list in use, and the section goes with nothing left.
    const restored = archivedFieldPatch(page, contact.id);
    await archivedRegion
      .getByRole('button', { name: `Restore ${old}` })
      .click();
    expect((await restored).status()).toBe(200);

    await expect(trigger).toBeHidden();
    await expect(methods.getByText(old)).toBeVisible();
  });
});
