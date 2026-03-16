/**
 * E2E Tests for Journal Contact Search (Typeahead)
 *
 * Tests that the ContactSearchCombobox on the journal detail page
 * correctly filters contacts by search query rather than always
 * returning the first page of all contacts.
 *
 * Regression test for bug: typeahead ignored search input and always
 * displayed the first page of contacts.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import type { Page } from '@playwright/test';

/**
 * Wait until MeiliSearch has indexed a contact matching the given search term.
 *
 * Uses Playwright's `expect.toPass()` for idiomatic retry/timeout behaviour
 * instead of manual `waitForTimeout` loops.  The request is made via
 * `page.request.get()` so it works even when the page has not navigated yet
 * (relative URLs resolve against the configured `baseURL`).
 */
async function waitForContactSearchIndexing(
  page: Page,
  searchTerm: string,
  expectedName: string,
  timeoutMs: number = 30_000
): Promise<void> {
  await expect(async () => {
    const res = await page.request.get(
      `/api/search/contacts?q=${encodeURIComponent(searchTerm)}&limit=20`
    );
    expect(res.ok()).toBe(true);

    const data = await res.json();
    const names = (
      (data.data as Array<{
        attributes?: { first_name?: string; last_name?: string };
      }>) ?? []
    ).map(c =>
      `${c.attributes?.first_name ?? ''} ${c.attributes?.last_name ?? ''}`.trim()
    );

    const found = names.some((n: string) =>
      n.toLowerCase().includes(expectedName.toLowerCase())
    );
    expect(found).toBe(true);
  }).toPass({
    timeout: timeoutMs,
    intervals: [1_000, 1_000, 2_000, 2_000, 5_000],
  });
}

test.describe('Journal Contact Search (Typeahead)', () => {
  test.describe('Contact search filtering', () => {
    test('should filter contacts by search query in the journal add-contact typeahead', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create two contacts with distinct names
      const contacts = await dataManager.createContacts([
        { firstName: 'Zephyr', lastName: 'Uniquename' },
        { firstName: 'Barnaby', lastName: 'Otherperson' },
      ]);

      // Create a journal to test on
      const journal = await dataManager.createJournal({
        title: 'Contact Search Test',
        content: 'Testing that contact search filters correctly.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
      });

      testCleanup(async () => await dataManager.cleanup());

      // Wait for contacts to be indexed in MeiliSearch
      // Use returned contact names which include the unique UUID suffix
      await waitForContactSearchIndexing(
        page,
        contacts[0].firstName,
        `${contacts[0].firstName} ${contacts[0].lastName}`
      );
      await waitForContactSearchIndexing(
        page,
        contacts[1].firstName,
        `${contacts[1].firstName} ${contacts[1].lastName}`
      );

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);

      // Open the add contact popover
      const addContactButton = page.getByTestId('add-contact-button');
      await expect(addContactButton).toBeVisible();
      await addContactButton.click();

      // Type a specific search term to filter contacts
      const contactSearchCombobox = page.getByPlaceholder(
        'Search for a contact...'
      );
      await expect(contactSearchCombobox).toBeVisible();
      await contactSearchCombobox.fill(contacts[0].firstName);

      // Wait for the search results listbox to appear
      await expect(page.getByRole('listbox')).toBeVisible({ timeout: 10000 });

      // Verify the matching contact IS shown
      const zephyrContactName = `${contacts[0].firstName} ${contacts[0].lastName}`;
      await expect(
        page.getByRole('option', { name: zephyrContactName })
      ).toBeVisible();

      // Verify the non-matching contact is NOT shown
      const barnabyContactName = `${contacts[1].firstName} ${contacts[1].lastName}`;
      await expect(
        page.getByRole('option', { name: barnabyContactName })
      ).not.toBeVisible();
    });

    test('should select a searched contact and add it to the journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Querencia',
        lastName: 'Typeahead',
      });

      // Create a journal
      const journal = await dataManager.createJournal({
        title: 'Contact Selection Test',
        content: 'Testing that selecting a searched contact works.',
        event_date_range: {
          start: '2026-01-19T10:00:00Z',
          end: '2026-01-19T10:30:00Z',
        },
        types: ['note'],
      });

      testCleanup(async () => await dataManager.cleanup());

      // Wait for the contact to be indexed in MeiliSearch
      // Use returned contact name which includes the unique UUID suffix
      await waitForContactSearchIndexing(
        page,
        contact.firstName,
        `${contact.firstName} ${contact.lastName}`
      );

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);

      // Open the add contact popover
      const addContactButton = page.getByTestId('add-contact-button');
      await expect(addContactButton).toBeVisible();
      await addContactButton.click();

      // Type the contact's name to search
      const contactName = `${contact.firstName} ${contact.lastName}`;
      const contactSearchCombobox = page.getByPlaceholder(
        'Search for a contact...'
      );
      await expect(contactSearchCombobox).toBeVisible();
      await contactSearchCombobox.fill(contact.firstName);

      // Wait for the search results and select the contact
      await expect(page.getByRole('listbox')).toBeVisible({ timeout: 10000 });
      await page.getByRole('option', { name: contactName }).click();

      // Verify the contact was selected (shown in the "Selected:" text)
      await expect(page.getByText(`Selected: ${contactName}`)).toBeVisible();

      // Confirm the addition
      await page.getByRole('button', { name: 'Add', exact: true }).click();

      // Verify the contact badge appears on the journal
      await expect(
        page.getByTestId(`contact-badge-${contact.id}`)
      ).toBeVisible();
    });
  });
});
