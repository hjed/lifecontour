/**
 * E2E Tests for Contact Journals Display
 *
 * Tests the integration of journals with the contact detail page,
 * including viewing journals grouped by relationship type and creating
 * new journals from the contact page.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import type { Page } from '@playwright/test';

/**
 * Helper function to navigate to contact page and wait for journals section
 */
async function navigateToContactAndWaitForJournals(
  page: Page,
  contactId: string
): Promise<void> {
  await page.goto(`/contacts/${contactId}`);
  await expect(page.getByRole('heading', { name: 'Journals' })).toBeVisible();
}

test.describe('Contact Journals Display', () => {
  test.describe('Viewing Journals on Contact Page', () => {
    test('should display journals section on contact detail page', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact with journals
      const contact = await dataManager.createContact({
        firstName: 'Test',
        lastName: 'User',
        email: 'test@example.com',
      });

      // Create journals with different relationship types
      const participantJournal = await dataManager.createJournal({
        title: 'Meeting with Test User',
        content: 'Discussed project plans',
        event_date_range: {
          start: '2024-01-15T10:00:00Z',
          end: '2024-01-15T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      const aboutJournal = await dataManager.createJournal({
        title: 'Notes about Test User',
        content: 'Important information about the contact',
        event_date_range: {
          start: '2024-01-16T14:00:00Z',
          end: '2024-01-16T14:30:00Z',
        },
        contacts: [{ contact_id: contact.id, relationship_type: 'ABOUT' }],
      });

      // Navigate to contact detail page
      await page.goto(`/contacts/${contact.id}`);

      // Wait for page to load by checking for contact name
      await expect(
        page.getByText(`${contact.firstName} ${contact.lastName}`)
      ).toBeVisible();

      // Verify journals section is visible
      await navigateToContactAndWaitForJournals(page, contact.id);

      // Verify participant journal is displayed
      await expect(
        page.getByRole('heading', { name: participantJournal.title })
      ).toBeVisible();

      // Verify about journal is displayed
      await expect(
        page.getByRole('heading', { name: aboutJournal.title })
      ).toBeVisible();
    });

    test('should group journals by relationship type with collapsible sections', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Jane',
        lastName: 'Doe',
        email: 'jane@example.com',
      });

      // Create journals with different relationship types
      await dataManager.createJournal({
        title: 'Participant Journal',
        content: 'Jane participated in this event',
        event_date_range: {
          start: '2024-01-15T10:00:00Z',
          end: '2024-01-15T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      await dataManager.createJournal({
        title: 'About Journal',
        content: 'This journal is about Jane',
        event_date_range: {
          start: '2024-01-16T14:00:00Z',
          end: '2024-01-16T14:30:00Z',
        },
        contacts: [{ contact_id: contact.id, relationship_type: 'ABOUT' }],
      });

      // Navigate to contact detail page and wait for journals section
      await navigateToContactAndWaitForJournals(page, contact.id);

      // Verify relationship type sections exist
      await expect(
        page.getByTestId('relationship-section-trigger-PARTICIPANT')
      ).toBeVisible();
      await expect(
        page.getByTestId('relationship-section-trigger-ABOUT')
      ).toBeVisible();

      // Test collapsible functionality
      const participantSection = page
        .locator('[data-state]')
        .filter({
          hasText: 'Participant',
        })
        .first();

      // Section should be collapsible (has data-state attribute)
      await expect(participantSection).toHaveAttribute('data-state', /.+/);
    });

    test('should display empty state when contact has no journals', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact without journals
      const contact = await dataManager.createContact({
        firstName: 'Empty',
        lastName: 'Contact',
        email: 'empty@example.com',
      });

      // Navigate to contact detail page and wait for journals section
      await navigateToContactAndWaitForJournals(page, contact.id);

      // Verify empty state message
      await expect(
        page.getByText(/no journals found for this contact/i)
      ).toBeVisible();
    });
  });

  test.describe('Navigating to Journal Details', () => {
    test('should navigate to journal detail page when clicking on a journal', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact with a journal
      const contact = await dataManager.createContact({
        firstName: 'Click',
        lastName: 'Test',
        email: 'click@example.com',
      });

      const journal = await dataManager.createJournal({
        title: 'Clickable Journal',
        content: 'This journal should be clickable',
        event_date_range: {
          start: '2024-01-15T10:00:00Z',
          end: '2024-01-15T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      // Navigate to contact detail page
      await page.goto(`/contacts/${contact.id}`);

      // Wait for journal to be visible
      await expect(
        page.getByRole('heading', { name: journal.title })
      ).toBeVisible();

      // Click on the journal
      await Promise.all([
        page.waitForURL(`**/journals/${journal.id}`),
        page.getByRole('heading', { name: journal.title }).click(),
      ]);

      // Verify we're on the journal detail page
      expect(page.url()).toContain(`/journals/${journal.id}`);
      await expect(
        page.getByRole('heading', { name: journal.title })
      ).toBeVisible();
      await expect(page.getByText(journal.content)).toBeVisible();
    });
  });

  test.describe('Creating Journals from Contact Page', () => {
    test('should navigate to create journal page with contact pre-filled', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Create',
        lastName: 'Test',
        email: 'create@example.com',
      });

      // Navigate to contact detail page and wait for journals section
      await navigateToContactAndWaitForJournals(page, contact.id);

      // Click the "Add Journal" button
      const addJournalButton = page.getByRole('link', { name: /add journal/i });
      await expect(addJournalButton).toBeVisible();

      await Promise.all([
        page.waitForURL(
          new RegExp(String.raw`/journals/new\?contact=${contact.id}`)
        ),
        addJournalButton.click(),
      ]);

      // Verify we're on the create journal page with contact parameter
      expect(page.url()).toContain('/journals/new');
      expect(page.url()).toContain(`contact=${contact.id}`);
    });

    test('should create journal and see it appear on contact page', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Full',
        lastName: 'Workflow',
        email: 'workflow@example.com',
      });

      // Navigate to contact detail page and wait for journals section
      await navigateToContactAndWaitForJournals(page, contact.id);

      // Verify empty state initially
      await expect(
        page.getByText(/no journals found for this contact/i)
      ).toBeVisible();

      // Create a journal for this contact
      const newJournal = await dataManager.createJournal({
        title: 'New Journal Entry',
        content: 'This journal was just created',
        event_date_range: {
          start: '2024-01-20T10:00:00Z',
          end: '2024-01-20T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      // Refresh the page to see the new journal
      await page.reload();

      // Wait for the new journal to appear
      await expect(
        page.getByRole('heading', { name: newJournal.title })
      ).toBeVisible({ timeout: 10000 });

      // Verify empty state is gone
      await expect(
        page.getByText(/no journals found for this contact/i)
      ).not.toBeVisible();
    });
  });
});
