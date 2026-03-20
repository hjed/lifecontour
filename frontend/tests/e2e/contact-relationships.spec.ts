/**
 * E2E Tests for Contact Relationships
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import type { Page } from '@playwright/test';

function attachClientErrorLogging(page: Page): void {
  page.on('pageerror', err => {
    console.error('[pageerror]', err);
  });
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.error('[console:error]', msg.text());
    }
  });
}

test.describe('Contact Relationships', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    attachClientErrorLogging(authenticatedPage);
  });

  test('should display relationship type options when adding a relationship', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a primary contact
    const contact = await dataManager.createContact({
      firstName: 'Primary',
      lastName: 'Contact',
      email: 'primary@example.com',
    });

    // Navigate to primary contact detail page
    await page.goto(`/contacts/${contact.id}`);

    // Wait for the page to load
    await expect(
      page.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible();

    // The relationships section should be visible
    await expect(
      page.getByRole('heading', { name: 'Relationships' })
    ).toBeVisible();

    // Click Add Relationship
    await page.getByRole('button', { name: 'Add Relationship' }).click();

    // Click the Relationship Type combobox/select.
    // Usually it's a combobox, let's open it and verify options.
    const typeLabel = page.getByLabel('Relationship Type');
    await typeLabel.click();

    // Verify that relationship types are loaded ("Parent", "Child", etc)
    // We expect at least these options to be in the listbox.
    const listbox = page.getByRole('listbox');
    await expect(
      listbox.getByRole('option', { name: 'Parent', exact: true })
    ).toBeVisible();
    await expect(
      listbox.getByRole('option', { name: 'Child', exact: true })
    ).toBeVisible();
    await expect(
      listbox.getByRole('option', { name: 'Spouse/Partner', exact: true })
    ).toBeVisible();

    // Select the first option
    await listbox.getByRole('option', { name: 'Parent', exact: true }).click();
  });
});
