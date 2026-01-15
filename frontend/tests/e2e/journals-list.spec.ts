/**
 * E2E Tests for Journal List Page
 *
 * Tests the integration of JournalList and JournalFilters components
 * in the /journals page.
 */

import { test, expect } from './fixtures';

test.describe('Journal List Page', () => {
  test.describe('Basic Display', () => {
    test('should display journals when data exists', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify page title
      await expect(page.locator('h1')).toContainText('Journals');

      // Verify journals are displayed
      for (const journal of journals) {
        // Check if journal title is visible
        await expect(
          page.getByRole('heading', { name: journal.title })
        ).toBeVisible();
      }
    });

    test('should display empty state when no journals exist', async ({
      emptyJournalsPage,
    }) => {
      const page = emptyJournalsPage;

      // Navigate to journals page
      await page.goto('/journals');

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify empty state is displayed
      await expect(page.getByText(/no journals found/i)).toBeVisible();
    });
  });

  test.describe('Filtering', () => {
    test.skip('should filter journals by search text', async ({
      journalsWithData,
    }) => {
      // SKIPPED: Journal text search is not implemented yet.
      // The JournalFilters component has a contact filter (ContactSearchCombobox)
      // but no general text search for journal titles/content.
      // This would require either:
      // 1. Adding a text search input to JournalFilters
      // 2. Using the backend search endpoint (GET /api/journals/search)
      const { page } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // TODO: Implement journal text search functionality
      // const searchInput = page.getByRole('textbox', { name: /search journals/i });
      // const searchTerm = journals[0].title.split('_')[0];
      // await searchInput.fill(searchTerm);
      // await page.waitForTimeout(500);
      // await expect(
      //   page.getByRole('heading', { name: new RegExp(searchTerm, 'i') })
      // ).toBeVisible();
    });

    test('should filter journals by type', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Verify all journals are initially visible
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', {
            name: new RegExp(journal.title, 'i'),
          })
        ).toBeVisible();
      }

      // Find the type filter checkbox within the filters section
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      const noteCheckbox = filtersSection.getByLabel('Note');

      // Check the NOTE type checkbox and wait for API response
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') && response.status() === 200
      );
      await noteCheckbox.check();
      await responsePromise;

      // Verify only note type journals are shown
      const noteJournal = journals.find(j => j.types?.includes('note'));
      if (noteJournal) {
        await expect(
          page.getByRole('heading', {
            name: new RegExp(noteJournal.title, 'i'),
          })
        ).toBeVisible();
      }

      // Verify non-note journals are not shown
      const nonNoteJournal = journals.find(j => !j.types?.includes('note'));
      if (nonNoteJournal) {
        await expect(
          page.getByRole('heading', {
            name: new RegExp(nonNoteJournal.title, 'i'),
          })
        ).not.toBeVisible();
      }
    });
  });

  test.describe('Navigation', () => {
    test('should navigate to journal detail when clicking a journal', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Click on the first journal link
      const firstJournal = journals[0];
      await page.getByRole('link', { name: firstJournal.title }).click();

      // Wait for navigation to complete
      await page.waitForURL(`**/journals/${firstJournal.id}`);

      // Verify we're on the detail page
      expect(page.url()).toContain(`/journals/${firstJournal.id}`);
    });

    test.skip('should navigate to create journal page when clicking create button', async ({
      emptyJournalsPage,
    }) => {
      // SKIPPED: Create button is currently disabled with "Coming soon" tooltip
      // This test will be enabled when journal creation is implemented
      const page = emptyJournalsPage;

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Find and click the create button
      const createButton = page.getByRole('button', { name: /create|new/i });
      if (
        (await createButton.isVisible()) &&
        !(await createButton.isDisabled())
      ) {
        await createButton.click();

        // Wait for navigation
        await page.waitForLoadState('networkidle');

        // Verify we're on the create page
        expect(page.url()).toContain('/journals/new');
      }
    });
  });
});
