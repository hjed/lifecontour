/**
 * E2E Tests for Journal List Page
 *
 * Tests the integration of JournalList and JournalFilters components
 * in the /journals page.
 */

import { test, expect } from './fixtures';
import { waitForContactSearchIndexing } from './utils/test-helpers';

/**
 * Generate an ISO datetime string offset from today by the given number of days.
 * Journals must use dates near "today" so they appear in the initial
 * date-window chunk loaded by the infinite scroll hook (~7 days around today).
 */
function relativeDate(dayOffset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  return d.toISOString();
}
test.describe('Journal List Page', () => {
  test.describe('Basic Display', () => {
    test('should display journals when data exists', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');

      // Wait for page to load
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // Verify the empty state card is displayed
      await expect(page.getByText('No journals found')).toBeVisible();
    });
  });

  test.describe('Filtering', () => {
    test('should filter journals by search text', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // Wait for journals to be indexed in MeiliSearch
      // The outbox processor runs every 10 seconds, so we retry this check
      // with Playwright's toPass polling until journals are indexed or timeout expires
      await expect(async () => {
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
        expect(response.ok).toBe(true);
        expect(response.count).toBeGreaterThan(0);
      }).toPass({ timeout: 15000 });

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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
            start: relativeDate(-2),
            end: relativeDate(-2),
          },
          // NOTE type (default)
        },
        {
          title: 'Team Meeting',
          content: 'Weekly sync with the team',
          event_date_range: {
            start: relativeDate(-1),
            end: relativeDate(-1),
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
            start: relativeDate(0),
            end: relativeDate(0),
          },
          // NOTE type (default)
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // Wait for journals to be indexed in MeiliSearch
      // Increased timeout to 30 seconds to handle indexing delays when running as part of full test suite
      await expect(async () => {
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

        expect(response.ok).toBe(true);
        expect(response.count).toBeGreaterThanOrEqual(2);

        const titles: string[] = response.titles ?? [];
        const hasMeetingNotes = titles.some(t =>
          t.toLowerCase().includes('meeting notes')
        );
        const hasTeamMeeting = titles.some(t =>
          t.toLowerCase().includes('team meeting')
        );

        expect(hasMeetingNotes).toBe(true);
        expect(hasTeamMeeting).toBe(true);
      }).toPass({ timeout: 30000 });

      // Search for "Meeting" - should match both "Meeting Notes" and "Team Meeting"
      const searchInput = page.getByTestId('search-input');
      await searchInput.fill('Meeting');

      // Wait for search results
      const meetingNotesHeading = page.getByRole('heading', {
        name: /Meeting Notes/i,
      });
      await expect(meetingNotesHeading).toBeVisible({ timeout: 30000 });

      const teamMeetingHeading = page.getByRole('heading', {
        name: /Team Meeting/i,
      });
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

      // Use dates relative to today so they appear in the initial chunk window.
      // We place all three journals within a few days of today so the infinite
      // scroll loads them, then apply a date range that includes only one.
      const today = new Date();
      const day1 = new Date(today);
      day1.setDate(today.getDate() - 2);
      const day2 = new Date(today);
      // day2 = today (no offset needed)
      const day3 = new Date(today);
      day3.setDate(today.getDate() + 2);

      const journals = await dataManager.createJournals([
        {
          title: 'Earlier Journal',
          content: 'This happened 2 days ago',
          event_date_range: {
            start: day1.toISOString(),
            end: day1.toISOString(),
          },
          types: ['note'],
        },
        {
          title: 'Middle Journal',
          content: 'This happened today',
          event_date_range: {
            start: day2.toISOString(),
            end: day2.toISOString(),
          },
          types: ['note'],
        },
        {
          title: 'Later Journal',
          content: 'This will happen in 2 days',
          event_date_range: {
            start: day3.toISOString(),
            end: day3.toISOString(),
          },
          types: ['note'],
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();
      // Wait for journal data to finish loading (prevents Mobile Chrome flakiness)
      await page.waitForLoadState('networkidle');

      // Verify all journals are initially visible (scrolling into view for mobile viewports)
      for (const journal of journals) {
        const heading = page.getByRole('heading', {
          name: new RegExp(journal.title, 'i'),
        });

        await expect(heading).toBeVisible({ timeout: 30000 });
      }

      // Open date range filter popover
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // Format the target dates for the calendar picker accessibility labels
      // The calendar buttons use labels like "9 April 2026"
      const monthNames = [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December',
      ];

      // Build the accessible name for the start/end date buttons
      // We want a range that only includes day2 (yesterday) but not day1 or day3
      const rangeStart = new Date(day2);
      rangeStart.setDate(rangeStart.getDate() - 1);
      const rangeEnd = new Date(day2);
      rangeEnd.setDate(rangeEnd.getDate() + 1);

      // Ensure the grid for the range start month is visible
      const startMonthName = `${monthNames[rangeStart.getMonth()]} ${rangeStart.getFullYear()}`;
      const startGrid = page.getByRole('grid', { name: startMonthName });
      // Navigate to the correct month if needed
      while (!(await startGrid.isVisible())) {
        const currentGrids = await page.getByRole('grid').allInnerTexts();
        await page
          .getByRole('button', { name: 'Go to the Previous Month' })
          .click();

        await expect(async () => {
          const newGrids = await page.getByRole('grid').allInnerTexts();
          expect(newGrids).not.toEqual(currentGrids);
        }).toPass({ timeout: 5000 });
      }

      const startLabel = `${rangeStart.getDate()} ${monthNames[rangeStart.getMonth()]} ${rangeStart.getFullYear()}`;
      await startGrid
        .getByRole('button', { name: new RegExp(`\\b${startLabel}\\b`) })
        .click();

      // Start waiting for API response before clicking the second date
      const responsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') &&
          response.url().includes('start_date') &&
          response.status() === 200
      );

      // Ensure the grid for the range end month is visible
      const endMonthName = `${monthNames[rangeEnd.getMonth()]} ${rangeEnd.getFullYear()}`;
      const endGrid = page.getByRole('grid', { name: endMonthName });
      while (!(await endGrid.isVisible())) {
        const currentGrids = await page.getByRole('grid').allInnerTexts();
        await page
          .getByRole('button', { name: 'Go to the Next Month' })
          .click();

        await expect(async () => {
          const newGrids = await page.getByRole('grid').allInnerTexts();
          expect(newGrids).not.toEqual(currentGrids);
        }).toPass({ timeout: 5000 });
      }

      const endLabel = `${rangeEnd.getDate()} ${monthNames[rangeEnd.getMonth()]} ${rangeEnd.getFullYear()}`;
      await endGrid
        .getByRole('button', { name: new RegExp(`\\b${endLabel}\\b`) })
        .click();

      // Wait for the API response to complete
      await responsePromise;

      // Verify only the Middle journal is visible (day2 is within the range)
      await expect(
        page.getByRole('heading', { name: /Middle Journal/i })
      ).toBeVisible();

      // Verify the other journals are not visible (outside the selected range)
      await expect(
        page.getByRole('heading', { name: /Earlier Journal/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Later Journal/i })
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
            start: relativeDate(-2),
            end: relativeDate(-2),
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
            start: relativeDate(-1),
            end: relativeDate(-1),
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
            start: relativeDate(0),
            end: relativeDate(0),
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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
            start: relativeDate(-2),
            end: relativeDate(-2),
          },
        },
        {
          title: 'Personal Note',
          content: 'Weekend plans',
          event_date_range: {
            start: relativeDate(-1),
            end: relativeDate(-1),
          },
        },
        {
          title: 'Mixed Journal',
          content: 'Both work and personal',
          event_date_range: {
            start: relativeDate(0),
            end: relativeDate(0),
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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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

      await expect(workHeading).toBeVisible({ timeout: 30000 });

      const mixedHeading = page.getByRole('heading', {
        name: /Mixed Journal/i,
      });

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

      // Use dates near today so journals appear in the initial chunk window.
      // today-1: Note with Charlie (matches all filters)
      // today:   Event with Charlie (wrong type)
      // today-3: Note with Charlie (wrong date — outside date-range filter)
      // today-2: Note without contact (wrong contact)
      const today = new Date();
      const day1 = new Date(today);
      day1.setDate(today.getDate() - 1);
      const day2 = new Date(today);
      const day3 = new Date(today);
      day3.setDate(today.getDate() - 3);
      const day4 = new Date(today);
      day4.setDate(today.getDate() - 2);

      await dataManager.createJournals([
        {
          title: 'Recent Note with Charlie',
          content: 'This matches all filters',
          event_date_range: {
            start: day1.toISOString(),
            end: day1.toISOString(),
          },
          // Don't specify types for NOTE - it's the default (no type-specific data)
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'Recent Event with Charlie',
          content: 'Wrong type',
          event_date_range: {
            start: day2.toISOString(),
            end: day2.toISOString(),
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
          title: 'Old Note with Charlie',
          content: 'Wrong date',
          event_date_range: {
            start: day3.toISOString(),
            end: day3.toISOString(),
          },
          // Don't specify types for NOTE - it's the default (no type-specific data)
          contacts: [
            { contact_id: contacts[0].id, relationship_type: 'PARTICIPANT' },
          ],
        },
        {
          title: 'Recent Note Solo',
          content: 'Wrong contact',
          event_date_range: {
            start: day4.toISOString(),
            end: day4.toISOString(),
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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // Apply date filter — select a range that includes day1 and day2 but excludes day3
      const dateRangeButton = page.getByRole('button', {
        name: /pick a date range/i,
      });
      await dateRangeButton.click();

      // Wait for calendar to be visible
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      const monthNames = [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December',
      ];

      // Build the date range: from day4 (today-2) to today
      // This excludes day3 (today-3) but includes day1 (today-1), day2 (today), day4 (today-2)
      const rangeStartMonthName = `${monthNames[day4.getMonth()]} ${day4.getFullYear()}`;
      const rangeStartGrid = page.getByRole('grid', {
        name: rangeStartMonthName,
      });
      while (!(await rangeStartGrid.isVisible())) {
        const currentGrids = await page.getByRole('grid').allInnerTexts();
        await page
          .getByRole('button', { name: 'Go to the Previous Month' })
          .click();

        await expect(async () => {
          const newGrids = await page.getByRole('grid').allInnerTexts();
          expect(newGrids).not.toEqual(currentGrids);
        }).toPass({ timeout: 5000 });
      }

      const startLabel = `${day4.getDate()} ${monthNames[day4.getMonth()]} ${day4.getFullYear()}`;
      await rangeStartGrid
        .getByRole('button', { name: new RegExp(`\\b${startLabel}\\b`) })
        .click();

      // Start waiting for API response before clicking the second date
      const dateResponsePromise = page.waitForResponse(
        response =>
          response.url().includes('/api/journals') && response.status() === 200
      );

      const rangeEndMonthName = `${monthNames[today.getMonth()]} ${today.getFullYear()}`;
      const rangeEndGrid = page.getByRole('grid', {
        name: rangeEndMonthName,
      });
      while (!(await rangeEndGrid.isVisible())) {
        const currentGrids = await page.getByRole('grid').allInnerTexts();
        await page
          .getByRole('button', { name: 'Go to the Next Month' })
          .click();

        await expect(async () => {
          const newGrids = await page.getByRole('grid').allInnerTexts();
          expect(newGrids).not.toEqual(currentGrids);
        }).toPass({ timeout: 5000 });
      }

      const endLabel = `${today.getDate()} ${monthNames[today.getMonth()]} ${today.getFullYear()}`;
      await rangeEndGrid
        .getByRole('button', { name: new RegExp(`\\b${endLabel}\\b`) })
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
        page.getByRole('heading', { name: /Recent Note with Charlie/i })
      ).toBeVisible();

      // Verify non-matching journals are not visible
      await expect(
        page.getByRole('heading', { name: /Recent Event with Charlie/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Old Note with Charlie/i })
      ).not.toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Recent Note Solo/i })
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
            start: relativeDate(-2),
            end: relativeDate(-2),
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
            start: relativeDate(-1),
            end: relativeDate(-1),
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
            start: relativeDate(0),
            end: relativeDate(0),
          },
        },
      ]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
          response.request().method() === 'GET' &&
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

      // Ensure the loading state has finished and the list is rendered again
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
          response.request().method() === 'GET' &&
          response.url().includes('/api/journals') &&
          response.url().includes('calendar_id') &&
          response.status() === 200
      );

      await calendarSelect.click();
      await page.getByRole('option', { name: /Personal Calendar/i }).click();
      await personalResponsePromise;

      // Ensure the loading state has finished and the list is rendered again
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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
            start: relativeDate(-3),
            end: relativeDate(-3),
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
            start: relativeDate(-2),
            end: relativeDate(-2),
          },
          parent_id: parentId,
        },
        {
          title: 'Child Journal 2',
          content: 'Second child',
          event_date_range: {
            start: relativeDate(-1),
            end: relativeDate(-1),
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
            start: relativeDate(0),
            end: relativeDate(0),
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
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

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

  test.describe('List View Refinements', () => {
    test('should jump to a specific date', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      await dataManager.clearAllJournals();

      const targetDate = new Date();
      targetDate.setDate(targetDate.getDate() + 15);
      const targetIso = targetDate.toISOString();

      const journals = await dataManager.createJournals([
        {
          title: 'Future Journal',
          content: 'A journal 15 days in the future',
          event_date_range: { start: targetIso, end: targetIso },
        },
      ]);
      const targetJournalTitle = journals[0].title;

      testCleanup(async () => await dataManager.cleanup());

      // Navigate to journals page
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // The future journal shouldn't be visible initially
      await expect(
        page.getByRole('heading', { name: targetJournalTitle })
      ).not.toBeVisible();

      // Click Date Jump Calendar
      const dateJumpBtn = page.getByTestId('jump-date-button');
      await dateJumpBtn.click();

      // Wait for calendar
      const monthNames = [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December',
      ];
      const targetMonthName = `${monthNames[targetDate.getMonth()]} ${targetDate.getFullYear()}`;
      const targetGrid = page.getByRole('grid', { name: targetMonthName });

      while (!(await targetGrid.isVisible())) {
        const currentGrids = await page.getByRole('grid').allInnerTexts();
        await page.getByRole('button', { name: /next month/i }).click();
        await expect(async () => {
          const newGrids = await page.getByRole('grid').allInnerTexts();
          expect(newGrids).not.toEqual(currentGrids);
        }).toPass({ timeout: 5000 });
      }

      await targetGrid
        .getByText(String(targetDate.getDate()), { exact: true })
        .first()
        .click();

      // Now the future journal should be in view!
      await expect(
        page.getByRole('heading', { name: targetJournalTitle })
      ).toBeVisible({ timeout: 15000 });
    });

    test('should collapse and expand empty week groups', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new (
        await import('./data-management')
      ).TestDataManager(page);

      await dataManager.clearAllJournals();

      const today = new Date();
      const past = new Date();
      past.setDate(today.getDate() - 8);

      await dataManager.createJournals([
        {
          title: 'Today Journal',
          content: 'Journal for today',
          event_date_range: {
            start: today.toISOString(),
            end: today.toISOString(),
          },
        },
        {
          title: 'Past Journal',
          content: 'Journal from 8 days ago',
          event_date_range: {
            start: past.toISOString(),
            end: past.toISOString(),
          },
        },
      ]);

      testCleanup(async () => await dataManager.cleanup());

      // Date jump backwards slightly so both load
      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // Wait for rendering
      // The empty days between (7 days empty) should be collapsed
      const collapsedText = page.getByText(/empty days/i);
      await expect(collapsedText).toBeVisible({ timeout: 15000 });

      // Click to expand
      const toggleBtn = page.getByRole('button', { name: /expand/i });
      await expect(toggleBtn).toBeVisible();
      await toggleBtn.click();

      // Expect to see "No journals for..." (the daily empty states)
      const emptyRow = page.getByText(/No journals for/i).first();
      await expect(emptyRow).toBeVisible();
    });
  });
});
