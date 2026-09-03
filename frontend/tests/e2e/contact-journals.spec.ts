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

function attachClientErrorLogging(page: Page): void {
  // Helpful for diagnosing generic Next.js “client-side exception” error pages.
  page.on('pageerror', err => {
    console.error('[pageerror]', err);
  });

  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.error('[console:error]', msg.text());
    }
  });
}

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
  test.beforeEach(async ({ authenticatedPage }) => {
    attachClientErrorLogging(authenticatedPage);
  });

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

      // Ensure the backend has both journal-contact relationships durably
      // readable before asserting on the UI. The journal + relationship create
      // commits at request teardown (after the create response is sent), so an
      // immediate page load can race ahead of the write — poll the API until it
      // is consistent, then the single UI load below is deterministic.
      await expect(async () => {
        const response = await page.request.get(
          `/api/contacts/${contact.id}/journals`
        );
        expect(response.ok()).toBeTruthy();
        const body = (await response.json()) as {
          data?: { id: string | number }[];
        };
        const ids = (body.data ?? []).map(journal => String(journal.id));
        expect(ids).toContain(String(participantJournal.id));
        expect(ids).toContain(String(aboutJournal.id));
      }).toPass({ timeout: 30000 });

      // Verify the journals section and both journals are displayed.
      await navigateToContactAndWaitForJournals(page, contact.id);
      await expect(
        page.getByRole('heading', { name: participantJournal.title })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: aboutJournal.title })
      ).toBeVisible();
    });

    test('should display contact name instead of Contact <id> on related journals', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Alice',
        lastName: 'Smith',
        email: 'alice.smith@example.com',
      });

      // Create a journal related to this contact
      const journal = await dataManager.createJournal({
        title: 'Meeting with Alice',
        content: 'Discussed project plans',
        event_date_range: {
          start: '2024-01-15T10:00:00Z',
          end: '2024-01-15T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      // Navigate to contact detail page and wait for journals section
      await navigateToContactAndWaitForJournals(page, contact.id);

      // The relationship is indexed asynchronously, so wait for it at the API
      // level first — polling the endpoint is a cheap request per attempt,
      // where the old reload-per-attempt loop paid a full page load every 2s
      // even when the data was already there. One reload then renders it.
      await expect(async () => {
        const response = await page.request.get(
          `/api/contacts/${contact.id}/journals?page=1&limit=20`
        );
        expect(response.ok()).toBeTruthy();
        const json = await response.json();
        const found = json.data.some(
          (entry: { id: string | number }) =>
            String(entry.id) === String(journal.id)
        );
        expect(found).toBe(true);
      }).toPass({ timeout: 30000 });

      await page.reload();
      const journalCard = page.getByTestId(`journal-${journal.id}`);
      await expect(journalCard).toBeVisible();

      // Verify that the contact's name is rendered in the journal's contact badges
      // It should NOT render as "Contact <id>"
      await expect(
        journalCard.getByRole('link', {
          name: new RegExp(
            `View ${contact.firstName} ${contact.lastName}`,
            'i'
          ),
        })
      ).toBeVisible();
      await expect(
        journalCard.getByRole('link', {
          name: new RegExp(`View Contact ${contact.id}`, 'i'),
        })
      ).toBeHidden();
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

      // Verify relationship type sections exist, using a retry loop for indexing
      await expect(async () => {
        await page.reload();
        await expect(
          page.getByTestId('relationship-section-trigger-PARTICIPANT')
        ).toBeVisible({ timeout: 2000 });
        await expect(
          page.getByTestId('relationship-section-trigger-ABOUT')
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

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

    test('should display parent/child hierarchy with expand/collapse', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a contact
      const contact = await dataManager.createContact({
        firstName: 'Hierarchy',
        lastName: 'Test',
        email: 'hierarchy@example.com',
      });

      // Create parent journal related to the contact
      const parentJournal = await dataManager.createJournal({
        title: 'Parent Journal',
        content: 'Parent content',
        event_date_range: {
          start: '2024-01-15T10:00:00Z',
          end: '2024-01-15T11:00:00Z',
        },
        contacts: [
          { contact_id: contact.id, relationship_type: 'PARTICIPANT' },
        ],
      });

      // Child is NOT directly related to the contact, but should still display
      // because it's a descendant of a related journal.
      const childJournal = await dataManager.createJournal({
        title: 'Child Journal',
        content: 'Child content',
        event_date_range: {
          start: '2024-01-16T10:00:00Z',
          end: '2024-01-16T11:00:00Z',
        },
        parent_id: Number(parentJournal.id),
      });

      await navigateToContactAndWaitForJournals(page, contact.id);

      // Parent should be visible, use retry loop for indexing
      await expect(async () => {
        await page.reload();
        await expect(
          page.getByRole('heading', { name: parentJournal.title })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

      // Child should render under parent's children container by default
      const childContainer = page.getByTestId(
        `journalChildrenContainer-${parentJournal.id}`
      );
      await expect(childContainer).toBeVisible();
      await expect(
        childContainer.getByRole('heading', { name: childJournal.title })
      ).toBeVisible();

      // Collapse children
      const toggle = page.getByTestId(
        `journalChildrenToggle-${parentJournal.id}`
      );
      await toggle.click();
      await expect(
        page.getByRole('heading', { name: childJournal.title })
      ).toHaveCount(0);

      // Expand children
      await toggle.click();
      await expect(
        childContainer.getByRole('heading', { name: childJournal.title })
      ).toBeVisible();

      // Navigation to child detail should still work
      await Promise.all([
        page.waitForURL(`**/journals/${childJournal.id}`),
        page.getByRole('heading', { name: childJournal.title }).click(),
      ]);
      await expect(
        page.getByRole('heading', { name: childJournal.title })
      ).toBeVisible();
      await expect(page.getByText(childJournal.content)).toBeVisible();
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

      // Wait for journal to be visible, use retry loop for indexing
      await expect(async () => {
        await page.reload();
        await expect(
          page.getByRole('heading', { name: journal.title })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

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

      // Wait for the new journal to appear, use retry loop for indexing
      await expect(async () => {
        await page.reload();
        await expect(
          page.getByRole('heading', { name: newJournal.title })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

      // Verify empty state is gone
      await expect(
        page.getByText(/no journals found for this contact/i)
      ).toBeHidden();
    });
  });
});
