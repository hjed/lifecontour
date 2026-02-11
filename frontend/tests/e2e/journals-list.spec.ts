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

    test('should filter journals by date range', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing journals
      await dataManager.clearAllJournals();

      // Create journals with different date ranges
      const journals = await dataManager.createJournals([
        {
          title: 'January Journal',
          content: 'This happened in January',
          event_date_range: {
            start: '2026-01-10T09:00:00Z',
            end: '2026-01-10T17:00:00Z',
          },
          types: ['note'],
        },
        {
          title: 'February Journal',
          content: 'This happened in February',
          event_date_range: {
            start: '2026-02-15T09:00:00Z',
            end: '2026-02-15T17:00:00Z',
          },
          types: ['note'],
        },
        {
          title: 'March Journal',
          content: 'This happened in March',
          event_date_range: {
            start: '2026-03-20T09:00:00Z',
            end: '2026-03-20T17:00:00Z',
          },
          types: ['note'],
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Verify all journals are initially visible
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', { name: new RegExp(journal.title, 'i') })
        ).toBeVisible();
      }

      // Open date range filter popover
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // Select dates within the February grid to avoid ambiguity with overflow dates
      const februaryGrid = page.getByRole('grid', { name: 'February 2026' });

      // Select start date (February 1, 2026)
      await februaryGrid
        .getByRole('button', { name: /\b1 February 2026\b/ })
        .click();

      // Start waiting for API response before clicking the second date
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('start_date') &&
          response.status() === 200
      );

      // Select end date (February 28, 2026) - this triggers the API call
      await februaryGrid
        .getByRole('button', { name: /\b28 February 2026\b/ })
        .click();

      // Wait for the API response to complete
      await responsePromise;

      // Verify only February journal is visible
      await expect(
        page.getByRole('heading', { name: /February Journal/i })
      ).toBeVisible();

      // Verify January and March journals are not visible
      await expect(
        page.getByRole('heading', { name: /January Journal/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /March Journal/i })
      ).not.toBeVisible();
    });

    test('should filter journals by contact', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();
      await dataManager.clearAllContacts();

      // Create test contacts
      const contacts = await dataManager.createContacts([
        { firstName: 'Alice', lastName: 'Smith' },
        { firstName: 'Bob', lastName: 'Jones' },
      ]);

      // Create journals with different contacts
      const journals = await dataManager.createJournals([
        {
          title: 'Meeting with Alice',
          content: 'Discussed project plans',
          event_date_range: {
            start: '2026-02-01T09:00:00Z',
            end: '2026-02-01T10:00:00Z',
          },
          types: ['note'],
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'Meeting with Bob',
          content: 'Reviewed quarterly goals',
          event_date_range: {
            start: '2026-02-02T09:00:00Z',
            end: '2026-02-02T10:00:00Z',
          },
          types: ['note'],
          contacts: [
            { contact_id: contacts[1].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'Solo Work',
          content: 'Working alone',
          event_date_range: {
            start: '2026-02-03T09:00:00Z',
            end: '2026-02-03T10:00:00Z',
          },
          types: ['note'],
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Verify all journals are initially visible
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', { name: new RegExp(journal.title, 'i') })
        ).toBeVisible();
      }

      // Use contact filter combobox - find by role and placeholder
      const contactCombobox = page.getByRole('combobox', {
        name: /search for a contact/i,
      });
      await contactCombobox.click();
      await contactCombobox.fill('Alice');

      // Wait for search results to appear by waiting for the option to be visible
      const aliceOption = page.getByText(/Alice.*Smith/i).first();
      await expect(aliceOption).toBeVisible();

      // Start waiting for API response before clicking the contact
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('contact_id') &&
          response.status() === 200
      );

      // Select Alice - this triggers the API call
      await aliceOption.click();

      // Wait for the API response to complete
      await responsePromise;

      // Verify only Alice's journal is visible
      await expect(
        page.getByRole('heading', { name: /Meeting with Alice/i })
      ).toBeVisible();

      // Verify other journals are not visible
      await expect(
        page.getByRole('heading', { name: /Meeting with Bob/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Solo Work/i })
      ).not.toBeVisible();
    });

    test.skip('should filter journals by tag', async () => {
      // SKIPPED: This test requires a POST /api/journals/tags endpoint to create journal tags
      // Currently, journal tags can only be created via the MCP tools (which use tag names)
      // or by assigning existing tags to journals via POST /api/journals/{id}/relationships/tags
      //
      // To enable this test, we need to either:
      // 1. Add a POST /api/journals/tags endpoint to create journal tags
      // 2. Seed the database with test journal tags
      // 3. Update the test to use the MCP tools to create journals with tag names
      //
      // For now, we're skipping this test and will implement it in a follow-up task.
      // Implementation pending POST /api/journals/tags endpoint (see Iteration A.5 in task doc)
    });

    test.skip('should filter journals with combined filters (date + type + contact)', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();
      await dataManager.clearAllContacts();

      // Create test contact
      const contacts = await dataManager.createContacts([
        { firstName: 'Charlie', lastName: 'Brown' },
      ]);

      // Create a test calendar for EVENT journals
      const calendars = await dataManager.createCalendars([
        { name: 'Test Calendar', color: '#FF0000' },
      ]);

      // Create journals with various combinations
      await dataManager.createJournals([
        {
          title: 'February Note with Charlie',
          content: 'This matches all filters',
          event_date_range: {
            start: '2026-02-10T09:00:00Z',
            end: '2026-02-10T17:00:00Z',
          },
          // Don't specify types for NOTE - it's the default (no type-specific data)
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'February Event with Charlie',
          content: 'Wrong type',
          event_date_range: {
            start: '2026-02-11T09:00:00Z',
            end: '2026-02-11T17:00:00Z',
          },
          types: ['event'],
          type_data: {
            event: {
              calendar_id: calendars[0].id,
              is_all_day: false,
              sync_invitees: false,
            },
          },
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'January Note with Charlie',
          content: 'Wrong date',
          event_date_range: {
            start: '2026-01-10T09:00:00Z',
            end: '2026-01-10T17:00:00Z',
          },
          // Don't specify types for NOTE - it's the default (no type-specific data)
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'February Note Solo',
          content: 'Wrong contact',
          event_date_range: {
            start: '2026-02-12T09:00:00Z',
            end: '2026-02-12T17:00:00Z',
          },
          // Don't specify types for NOTE - it's the default (no type-specific data)
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await page.waitForLoadState('networkidle');

      // Apply date filter (February 2026)
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // Select dates within the February grid to avoid ambiguity
      const februaryGrid = page.getByRole('grid', { name: 'February 2026' });
      await februaryGrid
        .getByRole('button', { name: /\b1 February 2026\b/ })
        .click();

      // Start waiting for API response before clicking the second date
      const dateResponsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') && response.status() === 200
      );

      await februaryGrid
        .getByRole('button', { name: /\b28 February 2026\b/ })
        .click();
      await dateResponsePromise;

      // Apply type filter (Note)
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      const noteCheckbox = filtersSection.getByLabel('Note', { exact: true });
      await noteCheckbox.check();

      // Apply contact filter (Charlie)
      const contactCombobox = page.getByRole('combobox', {
        name: /search for a contact/i,
      });
      await contactCombobox.click();
      await contactCombobox.fill('Charlie');

      // Wait for search results to appear by waiting for the option to be visible
      const charlieOption = page.getByText(/Charlie.*Brown/i).first();
      await expect(charlieOption).toBeVisible();

      // Start waiting for API response before clicking the contact
      const contactResponsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('start_date') &&
          response.url().includes('type=note') &&
          response.url().includes('contact_id') &&
          response.status() === 200
      );

      await charlieOption.click();

      // Wait for the API response to complete
      await contactResponsePromise;

      // Verify only the matching journal is visible
      await expect(
        page.getByRole('heading', { name: /February Note with Charlie/i })
      ).toBeVisible();

      // Verify non-matching journals are not visible
      await expect(
        page.getByRole('heading', { name: /February Event with Charlie/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /January Note with Charlie/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /February Note Solo/i })
      ).not.toBeVisible();
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
