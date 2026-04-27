/**
 * E2E Tests for Global Search
 *
 * Tests that the global header search box fetches live suggestions
 * and supports proper combobox navigation.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import { waitForContactSearchIndexing } from './utils/test-helpers';

test.describe('Global Header Search', () => {
  test('should display search suggestions from backend and navigate to contact', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'GlobalSearchTest',
      lastName: 'Contact',
    });

    testCleanup(async () => await dataManager.cleanup());

    // Wait for the contact to be indexed in MeiliSearch
    const contactName = `${contact.firstName} ${contact.lastName}`;
    await waitForContactSearchIndexing(page, contact.firstName, contactName);

    // Go to the dashboard
    await page.goto('/');

    // Locate the global search input in the header
    const searchInput = page.getByRole('combobox', { name: /global search/i });
    await expect(searchInput).toBeVisible();

    // Type the contact name
    await searchInput.fill(contact.firstName);

    // Wait for the listbox and options to appear
    const listbox = page.getByRole('listbox', { name: /search suggestions/i });
    await expect(listbox).toBeVisible({ timeout: 10000 });

    // Debug: print all options
    const options = await page.getByRole('option').allTextContents();
    console.log('Available options:', options);

    const option = page.getByRole('option', { name: contactName });
    await expect(option).toBeVisible({ timeout: 10000 });
    await expect(option).toBeVisible();

    // Click the suggestion
    await option.click();

    // Verify it navigates to the contact detail page
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));
  });
});
