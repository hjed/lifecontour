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
    test('should filter journals by search text', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Wait for journals to be indexed in MeiliSearch
      // The outbox processor runs every 10 seconds, so we poll until journals are indexed
      // We use a retry loop with exponential backoff
      let indexed = false;
      for (let attempt = 0; attempt < 15 && !indexed; attempt++) {
        await page.waitForTimeout(1000); // Wait 1 second between attempts

        // Check if journals are indexed by making a search request
        const response = await page.evaluate(async () => {
          try {
            const res = await fetch(
              '/api/journals/search?q=Weekend&limit=20&page=1'
            );
            if (!res.ok) return { ok: false, count: 0 };
            const data = await res.json();
            return { ok: true, count: data.data?.length || 0 };
          } catch {
            return { ok: false, count: 0 };
          }
        });

        if (response.ok && response.count > 0) {
          indexed = true;
        }
      }

      if (!indexed) {
        throw new Error(
          'Journals were not indexed in MeiliSearch within 15 seconds'
        );
      }

      // Verify all journals are initially visible
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', {
            name: new RegExp(journal.title, 'i'),
          })
        ).toBeVisible();
      }

      // Search for a specific journal by title
      // Use just "Weekend" to search for the first journal (Weekend Hike_xxx)
      const searchInput = page.getByTestId('search-input');
      const searchTerm = 'Weekend';

      await searchInput.fill(searchTerm);

      // Wait for the search to complete by checking that the matching journal is visible
      // This implicitly waits for the debounce and API call to complete
      await expect(
        page.getByRole('heading', {
          name: /Weekend Hike/i,
        })
      ).toBeVisible({ timeout: 5000 });

      // Verify non-matching journal is not visible (Team Meeting)
      await expect(
        page.getByRole('heading', {
          name: /Team Meeting/i,
        })
      ).not.toBeVisible();

      // Clear search
      const clearButton = page.getByTestId('clear-filters');
      await clearButton.click();

      // Wait for the search input to be cleared as a signal that filters are reset
      await expect(searchInput).toHaveValue('');

      // Verify all journals are visible again
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', {
            name: new RegExp(journal.title, 'i'),
          })
        ).toBeVisible();
      }
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
  });
});
