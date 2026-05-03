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
import { waitForContactSearchIndexing } from './utils/test-helpers';

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

      // Wait for the combobox to close before proceeding to avoid click interception
      await expect(page.getByRole('listbox')).toBeHidden();

      // Verify the contact was selected (shown as a badge)
      await expect(
        page.getByRole('button', { name: `Remove ${contactName}` })
      ).toBeVisible();

      // Confirm the addition
      await page.getByRole('button', { name: 'Add', exact: true }).click();

      // Verify the contact badge appears on the journal
      await expect(
        page.getByTestId(`contact-badge-${contact.id}`)
      ).toBeVisible();
    });
  });
});
