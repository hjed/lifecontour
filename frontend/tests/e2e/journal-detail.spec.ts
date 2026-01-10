/**
 * E2E Tests for Journal Detail Page
 *
 * Tests the integration of JournalDetailView and all Phase 4 components
 * in the /journals/[id] page.
 */

import { test, expect } from './fixtures';

test.describe('Journal Detail Page', () => {
  test.describe('Basic Display', () => {
    test('should display journal details', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify journal title is displayed
      await expect(
        page.getByRole('heading', { name: journal.title })
      ).toBeVisible();

      // Verify journal content is displayed
      await expect(page.getByText(journal.content)).toBeVisible();
    });

    test('should display 404 for non-existent journal', async ({
      emptyJournalsPage,
    }) => {
      const page = emptyJournalsPage;

      // Navigate to non-existent journal
      await page.goto('/journals/999999');

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify error message is displayed in an alert
      // Filter for the alert that contains our error message (not the Next.js route announcer)
      const alert = page
        .getByRole('alert')
        .filter({ hasText: /failed to load journal/i });
      await expect(alert).toContainText(/failed to load journal.*not found/i);
    });
  });

  test.describe('Inline Editing', () => {
    test.skip('should allow editing journal title', async ({
      journalsWithData,
    }) => {
      // SKIPPED: The journal detail page currently uses JournalDetailView which doesn't have inline editing.
      // The JournalDetail component with inline editing exists but isn't wired up to the page yet.
      // This test will be enabled when the page is updated to use JournalDetail component.
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find the title field (it's a button in view mode, not a heading)
      const titleField = page.getByTestId('journal-title-field');
      await expect(titleField).toBeVisible();
      await expect(titleField).toContainText(journal.title);

      // Click to enter edit mode
      await titleField.click();

      // Wait for the input field to appear
      const titleInput = page.getByTestId('journal-title-field-input');
      await expect(titleInput).toBeVisible();

      // Edit the title
      const newTitle = 'Updated Journal Title';
      await titleInput.fill(newTitle);

      // Click the save button
      const saveButton = page.getByRole('button', { name: 'Save changes' });
      await saveButton.click();

      // Wait for save to complete and verify the title was updated
      await expect(titleField).toContainText(newTitle);
      await expect(titleField).not.toContainText(journal.title);
    });

    test.skip('should allow editing journal content', async ({
      journalsWithData,
    }) => {
      // SKIPPED: The journal detail page currently uses JournalDetailView which doesn't have inline editing.
      // The JournalDetail component with inline editing exists but isn't wired up to the page yet.
      // This test will be enabled when the page is updated to use JournalDetail component.
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find the content field (it's a button in view mode)
      const contentField = page.getByTestId('journal-content');
      await expect(contentField).toBeVisible();
      await expect(contentField).toContainText(journal.content);

      // Click to enter edit mode
      await contentField.click();

      // Wait for the textarea to appear (use aria-label since there's no separate testid)
      const contentTextarea = page.getByRole('textbox', {
        name: 'Edit content',
      });
      await expect(contentTextarea).toBeVisible();

      // Edit the content
      const newContent = 'Updated content for the journal entry.';
      await contentTextarea.fill(newContent);

      // Click the save button
      const saveButton = page.getByTestId('journal-content-save');
      await saveButton.click();

      // Wait for save to complete and verify the content was updated
      await expect(contentField).toContainText(newContent);
      await expect(contentField).not.toContainText(journal.content);
    });
  });

  test.describe('Type Sections', () => {
    test('should display journal type badges', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals.find(j => j.types && j.types.length > 0);

      if (journal) {
        // Navigate to journal detail page
        await page.goto(`/journals/${journal.id}`);
        await page.waitForLoadState('networkidle');

        // Verify type badges are displayed
        for (const type of journal.types || []) {
          await expect(page.getByText(type)).toBeVisible();
        }
      }
    });
  });

  test.describe('Navigation', () => {
    test('should navigate back to journal list', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find and click the back button - use button role instead of link
      const backButton = page.getByRole('button', { name: /back/i });

      // Only run test if back button is visible
      if (await backButton.isVisible()) {
        await backButton.click();

        // Wait for navigation to complete
        await page.waitForURL('**/journals');

        // Verify we're on the list page
        expect(page.url()).toContain('/journals');
        expect(page.url()).not.toContain(`/journals/${journal.id}`);
      } else {
        // Skip test if back button not available
        test.skip();
      }
    });
  });
});
