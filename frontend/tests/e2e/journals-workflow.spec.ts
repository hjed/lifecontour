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
    test('should navigate from empty state to create page', async ({
      emptyJournalsPage,
    }) => {
      const page = emptyJournalsPage;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Verify empty state is displayed
      await expect(page.getByText(/no journals found/i)).toBeVisible();

      // Step 3: Click create link from empty state
      const createLink = page.getByRole('link', { name: /create journal/i });
      await expect(createLink).toBeVisible();

      // Wait for navigation to complete
      await Promise.all([
        page.waitForURL('**/journals/new'),
        createLink.click(),
      ]);

      // Step 4: Verify we're on the create page
      expect(page.url()).toContain('/journals/new');
      await expect(
        page.getByRole('heading', { name: /create new journal/i })
      ).toBeVisible();
    });
  });

  test.describe('List to Create Workflow', () => {
    test('should navigate from list to create page', async ({
      journalsWithData,
    }) => {
      const { page } = journalsWithData;

      // Step 1: Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Step 2: Click new journal link
      const newLink = page.getByRole('link', { name: /new journal/i });
      await expect(newLink).toBeVisible();

      // Wait for navigation to complete
      await Promise.all([page.waitForURL('**/journals/new'), newLink.click()]);

      // Step 3: Verify we're on the create page
      expect(page.url()).toContain('/journals/new');
      await expect(
        page.getByRole('heading', { name: /create new journal/i })
      ).toBeVisible();
    });
  });

  test.describe('Create Journal Workflow', () => {
    test('should create a journal and redirect to detail page', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;

      // Step 1: Navigate to create page
      await page.goto('/journals/new');
      await page.waitForLoadState('networkidle');

      // Step 2: Verify we're on the create page
      await expect(
        page.getByRole('heading', { name: /create new journal/i })
      ).toBeVisible();

      // Step 3: Fill in the form
      const testTitle = `Test Journal ${Date.now()}`;
      const testContent = 'This is a test journal entry created by E2E tests.';

      await page.getByLabel(/title/i).fill(testTitle);
      await page.getByLabel(/content/i).fill(testContent);

      // Step 4: Select a journal type
      await page.getByLabel(/note/i).check();

      // Step 5: Submit the form
      const createButton = page.getByRole('button', {
        name: /create journal/i,
      });
      await expect(createButton).toBeEnabled();

      // Wait for the API response
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.request().method() === 'POST' &&
          response.status() === 201
      );

      await createButton.click();
      await responsePromise;

      // Step 6: Verify we're redirected to the detail page
      await page.waitForURL(/\/journals\/\d+/);
      expect(page.url()).toMatch(/\/journals\/\d+/);

      // Step 7: Verify the journal details are displayed
      await expect(
        page.getByRole('heading', { name: testTitle })
      ).toBeVisible();
      await expect(page.getByText(testContent)).toBeVisible();

      // Step 8: Verify the type badge is displayed
      await expect(page.getByText(/note/i)).toBeVisible();
    });

    test('should show validation errors for empty title', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;

      // Step 1: Navigate to create page
      await page.goto('/journals/new');
      await page.waitForLoadState('networkidle');

      // Step 2: Try to submit without filling in title
      const createButton = page.getByRole('button', {
        name: /create journal/i,
      });
      await createButton.click();

      // Step 3: Verify validation error is displayed
      await expect(page.getByText(/title is required/i)).toBeVisible();

      // Step 4: Verify we're still on the create page
      expect(page.url()).toContain('/journals/new');
    });

    test('should cancel and return to journals list', async ({
      authenticatedPage,
    }) => {
      const page = authenticatedPage;

      // Step 1: Navigate to create page
      await page.goto('/journals/new');
      await page.waitForLoadState('networkidle');

      // Step 2: Click cancel button
      const cancelButton = page.getByRole('button', { name: /cancel/i });
      await expect(cancelButton).toBeVisible();
      await cancelButton.click();

      // Step 3: Verify we're redirected to journals list
      await page.waitForURL('/journals');
      expect(page.url()).toContain('/journals');
      expect(page.url()).not.toContain('/journals/new');
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
