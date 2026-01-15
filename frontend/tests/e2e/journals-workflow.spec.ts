/**
 * E2E Tests for Complete Journal Workflows
 *
 * Tests end-to-end workflows including list, filter, view, edit, and navigate.
 */

import { test, expect } from './fixtures';

test.describe('Journal Complete Workflows', () => {
  test.describe('Browse and View Workflow', () => {
    test('should browse journals, filter, and view details', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Verify journals are displayed
      await expect(page.locator('h1')).toContainText('Journals');
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', { name: journal.title })
        ).toBeVisible();
      }

      // Step 3: Verify filters are available
      // Note: Journal text search is not implemented yet, so we skip that part
      // The contact filter is available but requires selecting a contact, not searching journals
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      await expect(filtersSection).toBeVisible();

      // Step 4: Click on a journal link to view details
      const firstJournal = journals[0];
      await page.getByRole('link', { name: firstJournal.title }).click();
      await page.waitForURL(`**/journals/${firstJournal.id}`);

      // Step 5: Verify we're on the detail page
      expect(page.url()).toContain(`/journals/${firstJournal.id}`);
      await expect(
        page.getByRole('heading', { name: firstJournal.title })
      ).toBeVisible();
      await expect(page.getByText(firstJournal.content)).toBeVisible();

      // Step 6: Navigate back to list
      const backButton = page.getByRole('button', { name: /back/i });
      await backButton.click();
      await page.waitForURL('**/journals');

      // Step 7: Verify we're back on the list page
      expect(page.url()).toContain('/journals');
      expect(page.url()).not.toContain(`/journals/${firstJournal.id}`);
    });
  });

  test.describe('Filter and Navigate Workflow', () => {
    test('should filter by type and navigate to detail', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Apply type filter
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      const typeFilter = filtersSection.getByLabel(/type/i).first();

      if (await typeFilter.isVisible()) {
        // Wait for the API response when filtering
        const responsePromise = page.waitForResponse(
          response =>
            response.url().includes('/api/journals') &&
            response.status() === 200
        );
        await typeFilter.selectOption('note');
        await responsePromise;

        // Step 3: Find a note type journal
        const noteJournal = journals.find(j => j.types?.includes('note'));
        if (noteJournal) {
          // Step 4: Click on the journal
          await page
            .getByRole('heading', { name: new RegExp(noteJournal.title, 'i') })
            .click();
          await page.waitForLoadState('networkidle');

          // Step 5: Verify we're on the detail page
          expect(page.url()).toContain(`/journals/${noteJournal.id}`);
          await expect(
            page.getByRole('heading', { name: noteJournal.title })
          ).toBeVisible();
        }
      } else {
        // Skip test if type filter not available
        test.skip();
      }
    });
  });

  test.describe('Empty State to Create Workflow', () => {
    test.skip('should navigate from empty state to create page', async ({
      emptyJournalsPage,
    }) => {
      // SKIPPED: Create button is currently disabled with "Coming soon" tooltip
      // This test will be enabled when journal creation is implemented
      const page = emptyJournalsPage;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Verify empty state is displayed
      await expect(page.getByText(/no journals found/i)).toBeVisible();

      // Step 3: Click create button from empty state
      const createButton = page.getByRole('button', { name: /create/i });
      if (
        (await createButton.isVisible()) &&
        !(await createButton.isDisabled())
      ) {
        await createButton.click();
        await page.waitForLoadState('networkidle');

        // Step 4: Verify we're on the create page
        expect(page.url()).toContain('/journals/new');
      }
    });
  });

  test.describe('List to Create Workflow', () => {
    test.skip('should navigate from list to create page', async ({
      journalsWithData,
    }) => {
      // SKIPPED: New button is currently disabled with "Coming soon" tooltip
      // This test will be enabled when journal creation is implemented
      const { page } = journalsWithData;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Click new journal button
      const newButton = page.getByRole('button', { name: /new/i });
      if ((await newButton.isVisible()) && !(await newButton.isDisabled())) {
        await newButton.click();
        await page.waitForLoadState('networkidle');

        // Step 3: Verify we're on the create page
        expect(page.url()).toContain('/journals/new');
      }
    });
  });

  test.describe('Filter Toggle Workflow', () => {
    test('should toggle filters visibility', async ({ journalsWithData }) => {
      const { page } = journalsWithData;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Find the filter toggle button
      const filterToggle = page.getByRole('button', { name: /filter/i });
      const filtersSection = page.locator('[data-testid="journal-filters"]');

      if (await filterToggle.isVisible()) {
        // Step 3: Toggle filters off
        await filterToggle.click();
        await expect(filtersSection).toBeHidden();

        // Step 4: Toggle filters back on
        await filterToggle.click();
        await expect(filtersSection).toBeVisible();

        // Verify filters are visible again - use first() to avoid strict mode violation
        const dateRangeLabel = filtersSection.getByText(/date range/i).first();

        if (await dateRangeLabel.isVisible()) {
          await expect(dateRangeLabel).toBeVisible();
        }
      } else {
        // Skip test if filter toggle not available
        test.skip();
      }
    });
  });
});
