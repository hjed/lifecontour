/**
 * E2E Tests for Journal List Page
 *
 * Tests the integration of JournalList and JournalFilters components
 * in the /journals page.
 */

import { test, expect } from './fixtures';
import { waitForContactSearchIndexing } from './utils/test-helpers';

test.describe('Journal List Page', () => {
  test.describe('Basic Display', () => {
    test('should display journals when data exists', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');

      // Wait for page to load
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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
      const weekendHeading = page.getByRole('heading', {
        name: /Weekend Hike/i,
      });
      await weekendHeading.scrollIntoViewIfNeeded();
      await expect(weekendHeading).toBeVisible({ timeout: 30000 });

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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

    test('should combine search with type filter', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();

      // Create a calendar for EVENT journals
      const calendars = await dataManager.createCalendars([
        { name: 'Test Calendar', color: '#FF0000' },
      ]);

      // Create journals with different types
      await dataManager.createJournals([
        {
          title: 'Meeting Notes',
          content: 'Discussion about project timeline',
          event_date_range: {
            start: '2026-02-10T09:00:00Z',
            end: '2026-02-10T17:00:00Z',
          },
          // NOTE type (default)
        },
        {
          title: 'Team Meeting',
          content: 'Weekly sync with the team',
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
        },
        {
          title: 'Random Note',
          content: 'Some random thoughts',
          event_date_range: {
            start: '2026-02-12T09:00:00Z',
            end: '2026-02-12T17:00:00Z',
          },
          // NOTE type (default)
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Wait for journals to be indexed in MeiliSearch
      // Increased timeout to 30 seconds to handle indexing delays when running as part of full test suite
      let indexed = false;
      for (let attempt = 0; attempt < 30 && !indexed; attempt++) {
        await page.waitForTimeout(1000);

        const response = await page.evaluate(async () => {
          try {
            const res = await fetch(
              '/api/journals/search?q=Meeting&limit=20&page=1'
            );
            if (!res.ok) return { ok: false, count: 0, titles: [] };
            const data = await res.json();
            const titles = (data.data ?? []).map(
              (j: { attributes?: { title?: string } }) =>
                j.attributes?.title ?? ''
            );
            return { ok: true, count: titles.length, titles };
          } catch {
            return { ok: false, count: 0, titles: [] };
          }
        });

        // Wait for BOTH journals with "Meeting" in the title to be indexed ("Meeting Notes" and "Team Meeting")
        if (response.ok && response.count >= 2) {
          const titles: string[] = response.titles ?? [];
          const hasMeetingNotes = titles.some(t =>
            t.toLowerCase().includes('meeting notes')
          );
          const hasTeamMeeting = titles.some(t =>
            t.toLowerCase().includes('team meeting')
          );

          if (hasMeetingNotes && hasTeamMeeting) {
            indexed = true;
          }
        }
      }

      if (!indexed) {
        throw new Error(
          'Journals were not indexed in MeiliSearch within 30 seconds'
        );
      }

      // Search for "Meeting" - should match both "Meeting Notes" and "Team Meeting"
      const searchInput = page.getByTestId('search-input');
      await searchInput.fill('Meeting');

      // Wait for search results
      const meetingNotesHeading = page.getByRole('heading', {
        name: /Meeting Notes/i,
      });
      await meetingNotesHeading.scrollIntoViewIfNeeded();
      await expect(meetingNotesHeading).toBeVisible({ timeout: 30000 });

      const teamMeetingHeading = page.getByRole('heading', {
        name: /Team Meeting/i,
      });
      await teamMeetingHeading.scrollIntoViewIfNeeded();
      await expect(teamMeetingHeading).toBeVisible({ timeout: 30000 });

      // Now filter by EVENT type - should only show "Team Meeting"
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      const eventCheckbox = filtersSection.getByLabel('Event', { exact: true });

      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals/search') &&
          response.url().includes('types=event') &&
          response.status() === 200
      );

      await eventCheckbox.check();
      await responsePromise;

      // Should only show "Team Meeting" (EVENT type with "Meeting" in title)
      await expect(
        page.getByRole('heading', { name: /Team Meeting/i })
      ).toBeVisible();

      // "Meeting Notes" should not be visible (NOTE type, not EVENT)
      await expect(
        page.getByRole('heading', { name: /Meeting Notes/i })
      ).not.toBeVisible();

      // "Random Note" should not be visible (doesn't match search)
      await expect(
        page.getByRole('heading', { name: /Random Note/i })
      ).not.toBeVisible();
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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();
      // Wait for journal data to finish loading (prevents Mobile Chrome flakiness)
      await page.waitForLoadState('networkidle');

      // Verify all journals are initially visible (scrolling into view for mobile viewports)
      for (const journal of journals) {
        const heading = page.getByRole('heading', {
          name: new RegExp(journal.title, 'i'),
        });
        await heading.scrollIntoViewIfNeeded();
        await expect(heading).toBeVisible({ timeout: 30000 });
      }

      // Open date range filter popover
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // Navigate to February 2026 grid if not currently visible
      const februaryGrid = page.getByRole('grid', { name: 'February 2026' });
      while (!(await februaryGrid.isVisible())) {
        await page
          .getByRole('button', { name: 'Go to the Previous Month' })
          .click();
        // Wait for the calendar to update before checking visibility again
        await expect(page.getByRole('status').first()).toBeVisible();
      }

      // Select dates within the February grid to avoid ambiguity with overflow dates

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

      // Wait for MeiliSearch to index the contacts before searching
      await waitForContactSearchIndexing(
        page,
        contacts[0].firstName,
        `${contacts[0].firstName} ${contacts[0].lastName}`
      );

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Verify all journals are initially visible
      for (const journal of journals) {
        await expect(
          page.getByRole('heading', { name: new RegExp(journal.title, 'i') })
        ).toBeVisible();
      }

      // Use contact filter combobox - find by role and placeholder
      // Use the unique firstName (e.g. Alice_60417bb1) to avoid matching
      // stale MeiliSearch entries from previous test runs/retries
      const contactCombobox = page.getByRole('combobox', {
        name: /search for a contact/i,
      });
      await contactCombobox.click();
      await contactCombobox.fill(contacts[0].firstName);

      // Wait for search results to appear by waiting for the option to be visible
      const aliceOption = page.getByRole('option', {
        name: new RegExp(
          `${contacts[0].firstName}.*${contacts[0].lastName}`,
          'i'
        ),
      });
      await expect(aliceOption).toBeVisible();

      // Start waiting for API response before clicking the contact
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('contact_id') &&
          response.status() === 200 &&
          response.request().method() === 'GET'
      );

      // Select Alice - this triggers the API call
      await aliceOption.click();

      // Wait for the API response to complete
      await responsePromise;

      // Verify only Alice's journal is shown
      const aliceHeading = page.getByRole('heading', {
        name: /Meeting with Alice/i,
      });
      await aliceHeading.scrollIntoViewIfNeeded();
      await expect(aliceHeading).toBeVisible({ timeout: 30000 });

      // Verify contact name is visible on the journal card
      await expect(
        page.getByTestId(`contact-${contacts[0].id}`).first()
      ).toContainText(`${contacts[0].firstName} ${contacts[0].lastName}`);

      // Verify other journals are not visible
      await expect(
        page.getByRole('heading', { name: /Meeting with Bob/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Solo Work/i })
      ).not.toBeVisible();
    });

    test('should filter journals by tag', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();

      // Create journal tags
      const tags = await dataManager.createJournalTags([
        { name: 'Work', color: '#FF0000' },
        { name: 'Personal', color: '#00FF00' },
      ]);

      // Create journals
      const journals = await dataManager.createJournals([
        {
          title: 'Work Meeting',
          content: 'Quarterly review',
          event_date_range: {
            start: '2026-02-10T09:00:00Z',
            end: '2026-02-10T17:00:00Z',
          },
        },
        {
          title: 'Personal Note',
          content: 'Weekend plans',
          event_date_range: {
            start: '2026-02-11T09:00:00Z',
            end: '2026-02-11T17:00:00Z',
          },
        },
        {
          title: 'Mixed Journal',
          content: 'Both work and personal',
          event_date_range: {
            start: '2026-02-12T09:00:00Z',
            end: '2026-02-12T17:00:00Z',
          },
        },
      ]);

      // Assign tags to journals
      await dataManager.assignTagsToJournal(journals[0].id, [tags[0].id]); // Work tag
      await dataManager.assignTagsToJournal(journals[1].id, [tags[1].id]); // Personal tag
      await dataManager.assignTagsToJournal(journals[2].id, [
        tags[0].id,
        tags[1].id,
      ]); // Both tags

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Verify all journals are initially visible
      await expect(
        page.getByRole('heading', { name: /Work Meeting/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Personal Note/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Mixed Journal/i })
      ).toBeVisible();

      // Wait for tags to load in the filter panel
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      await expect(filtersSection.getByText(tags[0].name)).toBeVisible();

      // Filter by Work tag (use the exact tag name returned from creation)
      const workCheckbox = filtersSection.getByLabel(tags[0].name);

      // Start waiting for API response before checking the checkbox
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('tag_id') &&
          response.status() === 200
      );

      await workCheckbox.check();
      await responsePromise;

      // Verify only journals with Work tag are visible
      const workHeading = page.getByRole('heading', { name: /Work Meeting/i });
      await workHeading.scrollIntoViewIfNeeded();
      await expect(workHeading).toBeVisible({ timeout: 30000 });

      const mixedHeading = page.getByRole('heading', {
        name: /Mixed Journal/i,
      });
      await mixedHeading.scrollIntoViewIfNeeded();
      await expect(mixedHeading).toBeVisible({ timeout: 30000 });

      // Verify Personal Note is not visible
      await expect(
        page.getByRole('heading', { name: /Personal Note/i })
      ).not.toBeVisible();

      // Uncheck Work tag
      await workCheckbox.uncheck();

      // Wait for all journals to be visible again
      await expect(
        page.getByRole('heading', { name: /Personal Note/i })
      ).toBeVisible();

      // Filter by Personal tag (use the exact tag name returned from creation)
      const personalCheckbox = filtersSection.getByLabel(tags[1].name);

      const personalResponsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('tag_id') &&
          response.status() === 200
      );

      await personalCheckbox.check();
      await personalResponsePromise;

      // Verify only journals with Personal tag are visible
      await expect(
        page.getByRole('heading', { name: /Personal Note/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Mixed Journal/i })
      ).toBeVisible();

      // Verify Work Meeting is not visible
      await expect(
        page.getByRole('heading', { name: /Work Meeting/i })
      ).not.toBeVisible();
    });

    test('should filter journals with combined filters (date + type + contact)', async ({
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

      // Wait for MeiliSearch to index the contact before searching
      await waitForContactSearchIndexing(
        page,
        contacts[0].firstName,
        `${contacts[0].firstName} ${contacts[0].lastName}`
      );

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Apply date filter (February 2026)
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // Navigate to February 2026 grid if not currently visible
      const februaryGrid = page.getByRole('grid', { name: 'February 2026' });
      while (!(await februaryGrid.isVisible())) {
        await page
          .getByRole('button', { name: 'Go to the Previous Month' })
          .click();
        // Wait for the calendar to update before checking visibility again
        await expect(page.getByRole('status').first()).toBeVisible();
      }

      // Select dates within the February grid to avoid ambiguity
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

      // Apply contact filter (Charlie) using unique firstName to avoid
      // matching stale MeiliSearch entries from previous test runs/retries
      const contactCombobox = page.getByRole('combobox', {
        name: /search for a contact/i,
      });
      await contactCombobox.click();
      await contactCombobox.fill(contacts[0].firstName);

      // Wait for search results to appear by waiting for the option to be visible
      const charlieOption = page.getByRole('option', {
        name: new RegExp(
          `${contacts[0].firstName}.*${contacts[0].lastName}`,
          'i'
        ),
      });
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

    test('should filter journals by calendar', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();

      // Create test calendars
      const calendars = await dataManager.createCalendars([
        { name: 'Work Calendar', color: '#FF0000' },
        { name: 'Personal Calendar', color: '#00FF00' },
      ]);

      // Create journals with different calendars
      await dataManager.createJournals([
        {
          title: 'Work Event',
          content: 'Team meeting',
          event_date_range: {
            start: '2026-02-10T09:00:00Z',
            end: '2026-02-10T17:00:00Z',
          },
          types: ['event'],
          type_data: {
            event: {
              calendar_id: calendars[0].id,
              is_all_day: false,
              sync_invitees: false,
            },
          },
        },
        {
          title: 'Personal Event',
          content: 'Dentist appointment',
          event_date_range: {
            start: '2026-02-11T09:00:00Z',
            end: '2026-02-11T17:00:00Z',
          },
          types: ['event'],
          type_data: {
            event: {
              calendar_id: calendars[1].id,
              is_all_day: false,
              sync_invitees: false,
            },
          },
        },
        {
          title: 'Note without Calendar',
          content: 'Random note',
          event_date_range: {
            start: '2026-02-12T09:00:00Z',
            end: '2026-02-12T17:00:00Z',
          },
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Verify all journals are initially visible
      await expect(
        page.getByRole('heading', { name: /Work Event/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Personal Event/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Note without Calendar/i })
      ).toBeVisible();

      // Filter by Work Calendar
      const filtersSection = page.locator('[data-testid="journal-filters"]');
      const calendarSelect = filtersSection.getByRole('combobox', {
        name: /calendar/i,
      });

      // Start waiting for API response before selecting calendar
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('calendar_id') &&
          response.status() === 200
      );

      await calendarSelect.click();
      await page
        .getByRole('option', { name: /Work Calendar/i })
        .first()
        .click();
      await responsePromise;

      // Verify only Work Event is visible
      await expect(
        page.getByRole('heading', { name: /Work Event/i })
      ).toBeVisible();

      // Verify other journals are not visible
      await expect(
        page.getByRole('heading', { name: /Personal Event/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Note without Calendar/i })
      ).not.toBeVisible();

      // Change to Personal Calendar
      const personalResponsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('calendar_id') &&
          response.status() === 200
      );

      await calendarSelect.click();
      await page.getByRole('option', { name: /Personal Calendar/i }).click();
      await personalResponsePromise;

      // Verify only Personal Event is visible
      await expect(
        page.getByRole('heading', { name: /Personal Event/i })
      ).toBeVisible();

      // Verify other journals are not visible
      await expect(
        page.getByRole('heading', { name: /Work Event/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Note without Calendar/i })
      ).not.toBeVisible();

      // Select "All calendars" to clear filter
      await calendarSelect.click();
      await page.getByRole('option', { name: /All calendars/i }).click();

      // Wait for the filter to be cleared and all journals to be visible
      await expect(
        page.getByRole('heading', { name: /Work Event/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Personal Event/i })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Note without Calendar/i })
      ).toBeVisible();
    });

    test('should filter journals by parent (API level)', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      // Clear existing data
      await dataManager.clearAllJournals();

      // Create a parent journal
      const parentJournals = await dataManager.createJournals([
        {
          title: 'Parent Journal',
          content: 'This is a parent journal',
          event_date_range: {
            start: '2026-02-10T09:00:00Z',
            end: '2026-02-10T17:00:00Z',
          },
        },
      ]);

      const parentId = Number.parseInt(parentJournals[0].id, 10);

      // Create child journals
      await dataManager.createJournals([
        {
          title: 'Child Journal 1',
          content: 'First child',
          event_date_range: {
            start: '2026-02-11T09:00:00Z',
            end: '2026-02-11T17:00:00Z',
          },
          parent_id: parentId,
        },
        {
          title: 'Child Journal 2',
          content: 'Second child',
          event_date_range: {
            start: '2026-02-12T09:00:00Z',
            end: '2026-02-12T17:00:00Z',
          },
          parent_id: parentId,
        },
      ]);

      // Create another root journal (no parent)
      await dataManager.createJournals([
        {
          title: 'Another Root Journal',
          content: 'This is another root journal',
          event_date_range: {
            start: '2026-02-13T09:00:00Z',
            end: '2026-02-13T17:00:00Z',
          },
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Test 1: Filter by parent_id to get only children of the parent journal
      const childrenResponse = await page.request.get(
        `/api/journals?parent_id=${parentId}`
      );
      expect(childrenResponse.ok()).toBeTruthy();

      const childrenData = await childrenResponse.json();
      expect(childrenData.data).toHaveLength(2);

      const childTitles = childrenData.data.map(
        (j: { attributes: { title: string } }) => j.attributes.title
      );
      // Titles have random suffixes, so we need to check if they start with the expected text
      expect(
        childTitles.some((t: string) => t.startsWith('Child Journal 1'))
      ).toBe(true);
      expect(
        childTitles.some((t: string) => t.startsWith('Child Journal 2'))
      ).toBe(true);
      expect(
        childTitles.some((t: string) => t.startsWith('Parent Journal'))
      ).toBe(false);
      expect(
        childTitles.some((t: string) => t.startsWith('Another Root Journal'))
      ).toBe(false);

      // Test 2: Get all journals (no parent filter) - should return all 4 journals
      const allJournalsResponse = await page.request.get('/api/journals');
      expect(allJournalsResponse.ok()).toBeTruthy();

      const allJournalsData = await allJournalsResponse.json();
      expect(allJournalsData.data.length).toBeGreaterThanOrEqual(4);

      const allTitles = allJournalsData.data.map(
        (j: { attributes: { title: string } }) => j.attributes.title
      );
      // Use partial matching since journals have unique suffixes
      expect(
        allTitles.some((t: string) => t.startsWith('Parent Journal'))
      ).toBe(true);
      expect(
        allTitles.some((t: string) => t.startsWith('Child Journal 1'))
      ).toBe(true);
      expect(
        allTitles.some((t: string) => t.startsWith('Child Journal 2'))
      ).toBe(true);
      expect(
        allTitles.some((t: string) => t.startsWith('Another Root Journal'))
      ).toBe(true);
    });
  });

  test.describe('Navigation', () => {
    test('should navigate to journal detail when clicking a journal', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Click on the first journal link
      const firstJournal = journals[0];
      await page.getByRole('link', { name: firstJournal.title }).click();

      // Wait for navigation to complete
      await page.waitForURL(`**/journals/${firstJournal.id}`);

      // Verify we're on the detail page
      expect(page.url()).toContain(`/journals/${firstJournal.id}`);
    });
  });

  test.describe('Date Window API', () => {
    /**
     * Format a Date as YYYY-MM-DD in the user's local timezone.
     * Using local timezone avoids ±1 day drift when running near midnight UTC.
     */
    const toLocalDateString = (d: Date): string => {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    };

    test('should return journals anchored to the current day within the default window', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      await dataManager.clearAllJournals();

      // Get today's date and create journals at different offsets
      const today = new Date();
      const todayIso = today.toISOString();
      const thirtyDaysAgo = new Date(today);
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
      const thirtyDaysAgoIso = thirtyDaysAgo.toISOString();

      const journals = await dataManager.createJournals([
        {
          title: 'Today Journal',
          content: 'A journal created for today.',
          event_date_range: {
            start: todayIso,
            end: todayIso,
          },
        },
        {
          title: 'Old Journal',
          content: 'A journal from 30 days ago.',
          event_date_range: {
            start: thirtyDaysAgoIso,
            end: thirtyDaysAgoIso,
          },
        },
      ]);

      // Use the returned titles (which include unique suffixes from createJournals)
      const todayJournalTitle = journals[0].title;
      const oldJournalTitle = journals[1].title;

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Query the REST API with a date window anchored to today (default 2 days back, 4 days forward)
      // Use local timezone dates to match the backend's date interpretation
      const windowStart = new Date(today);
      windowStart.setDate(windowStart.getDate() - 2);
      const windowEnd = new Date(today);
      windowEnd.setDate(windowEnd.getDate() + 4);

      const startDate = toLocalDateString(windowStart);
      const endDate = toLocalDateString(windowEnd);

      const response = await page.request.get(
        `/api/journals?start_date=${startDate}&end_date=${endDate}&limit=20`
      );
      expect(response.ok()).toBe(true);

      const body = await response.json();
      const titles = body.data.map(
        (j: { attributes: { title: string } }) => j.attributes.title
      );

      // Today's journal should be in the window
      expect(titles).toContain(todayJournalTitle);
      // The old journal (30 days ago) should NOT be in the window
      expect(titles).not.toContain(oldJournalTitle);
    });

    test('should return correct pagination metadata', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      await dataManager.clearAllJournals();

      const today = new Date().toISOString();

      // Create 3 journals all on today's date
      await dataManager.createJournals(
        Array.from({ length: 3 }, (_, i) => ({
          title: `Pagination Journal ${i + 1}`,
          content: `Content for pagination test ${i + 1}`,
          event_date_range: { start: today, end: today },
        }))
      );

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Use local timezone dates to match the backend's date interpretation
      const windowStart = new Date();
      windowStart.setDate(windowStart.getDate() - 2);
      const windowEnd = new Date();
      windowEnd.setDate(windowEnd.getDate() + 4);

      const startDate = toLocalDateString(windowStart);
      const endDate = toLocalDateString(windowEnd);

      // Request with limit=2 to force pagination
      const response = await page.request.get(
        `/api/journals?start_date=${startDate}&end_date=${endDate}&limit=2&page=1`
      );
      expect(response.ok()).toBe(true);

      const body = await response.json();

      // Verify pagination meta (JSON API field names)
      expect(body.data).toHaveLength(2);
      expect(body.meta.total_count).toBe(3);
      expect(body.meta.current_page).toBe(1);
      expect(body.meta.page_count).toBeGreaterThanOrEqual(2);
    });
  });
});
