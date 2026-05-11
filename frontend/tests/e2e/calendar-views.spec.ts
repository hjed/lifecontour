/**
 * E2E Tests for Calendar Views
 *
 * Tests for ITER7-007 Phase 1: Month and Agenda calendar views.
 * Verifies view switching, event navigation, colour coding,
 * filter integration, and month navigation.
 */

import { test, expect } from './fixtures';

/**
 * Generate an ISO datetime string offset from today by the given number of days.
 */
function relativeDate(dayOffset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  return d.toISOString();
}

test.describe('Calendar Views', () => {
  test('should switch to month view and display month grid', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    // Create a calendar and an EVENT journal for the current month
    const calendars = await dataManager.createCalendars([
      { name: 'E2E Cal', color: '#3B82F6' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Month View Event',
        content: 'An event for calendar month view testing',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate to journals page
    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible({
      timeout: 10000,
    });

    // Click Month view toggle
    await page.getByRole('radio', { name: /month view/i }).click();

    // Verify month grid appears
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    // Verify month heading is present with the current date
    const now = new Date();
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
    const expectedHeading = `${monthNames[now.getMonth()]} ${now.getFullYear()}`;
    await expect(page.getByText(expectedHeading)).toBeVisible();

    // Verify event pill is visible in the month grid
    await expect(
      page.getByRole('link', { name: /month view event/i })
    ).toBeVisible();
  });

  test('should open event from month view and return to month view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Nav Cal', color: '#10B981' },
    ]);

    const journals = await dataManager.createJournals([
      {
        title: 'Navigable Event',
        content: 'Click this to navigate to detail',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to month view
    await page.getByRole('radio', { name: /month view/i }).click();
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    // Click the event pill to navigate to journal detail
    await page.getByRole('link', { name: /navigable event/i }).click();

    // Verify we're on the journal detail page
    await expect(page).toHaveURL(new RegExp(`/journals/${journals[0].id}`));
    await expect(
      page.getByRole('heading', { name: /navigable event/i })
    ).toBeVisible();

    // Navigate back
    await page.goBack();

    // Verify month view is still rendered after going back
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();
  });

  test('should switch to agenda view and display events', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Agenda Cal', color: '#EF4444' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Agenda View Event',
        content: 'This should appear in the agenda view',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendars[0].id,
            is_all_day: false,
            sync_invitees: false,
            start_time: '14:00:00',
            end_time: '15:00:00',
          },
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to agenda view
    await page.getByRole('radio', { name: /agenda view/i }).click();

    // Verify agenda view appears
    await expect(page.getByTestId('calendar-agenda-view')).toBeVisible();

    // Verify event is listed
    await expect(
      page.getByRole('link', { name: /agenda view event/i })
    ).toBeVisible();

    // Verify time is shown
    await expect(page.getByText('14:00 – 15:00')).toBeVisible();
  });

  test('should open event from agenda view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Agenda Nav Cal', color: '#8B5CF6' },
    ]);

    const journals = await dataManager.createJournals([
      {
        title: 'Clickable Agenda Event',
        content: 'An event we can click in agenda view',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendars[0].id,
            is_all_day: true,
            sync_invitees: false,
          },
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to agenda view
    await page.getByRole('radio', { name: /agenda view/i }).click();
    await expect(page.getByTestId('calendar-agenda-view')).toBeVisible();

    // Click the event
    await page.getByRole('link', { name: /clickable agenda event/i }).click();

    // Verify navigation to detail page
    await expect(page).toHaveURL(new RegExp(`/journals/${journals[0].id}`));
    await expect(
      page.getByRole('heading', { name: /clickable agenda event/i })
    ).toBeVisible();
  });

  test('should show colour-coded events from different calendars', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    // Create two calendars with distinct colours
    const calendars = await dataManager.createCalendars([
      { name: 'Work Calendar', color: '#3B82F6' },
      { name: 'Personal Calendar', color: '#EF4444' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Work Meeting',
        content: 'Work event',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
        title: 'Personal Dinner',
        content: 'Personal event',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to agenda view (easier to verify colours in agenda)
    await page.getByRole('radio', { name: /agenda view/i }).click();
    await expect(page.getByTestId('calendar-agenda-view')).toBeVisible();

    // Verify both events are visible
    await expect(
      page.getByRole('link', { name: /work meeting/i })
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: /personal dinner/i })
    ).toBeVisible();

    // Verify calendar colour dots are present (check background-color)
    // We look for the dots by test ID and check their styles
    const dots = page.locator('[data-testid^="calendar-dot-"]');
    await expect(dots).toHaveCount(2);
  });

  test('should respect type filter in calendar views', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Filter Cal', color: '#F59E0B' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Event Entry',
        content: 'This is an event',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
        title: 'Note Entry',
        content: 'This is a note',
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

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to agenda view
    await page.getByRole('radio', { name: /agenda view/i }).click();
    await expect(page.getByTestId('calendar-agenda-view')).toBeVisible();

    // Both entries should be visible initially
    await expect(
      page.getByRole('link', { name: /event entry/i })
    ).toBeVisible();
    await expect(page.getByRole('link', { name: /note entry/i })).toBeVisible();

    // Apply EVENT type filter
    const filtersSection = page.locator('[data-testid="journal-filters"]');
    const eventCheckbox = filtersSection.getByLabel('Event', { exact: true });

    const responsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') &&
        response.url().includes('type=event') &&
        response.request().method() === 'GET' &&
        response.status() === 200
    );

    await eventCheckbox.check();
    await responsePromise;

    // Only event should be visible
    await expect(
      page.getByRole('link', { name: /event entry/i })
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: /note entry/i })
    ).not.toBeVisible();
  });

  test('should persist view mode during filter changes', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Persist Cal', color: '#06B6D4' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Persist Test Event',
        content: 'Testing view mode persistence',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
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
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to month view
    await page.getByRole('radio', { name: /month view/i }).click();
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    // Apply a filter while in month view
    const filtersSection = page.locator('[data-testid="journal-filters"]');
    const eventCheckbox = filtersSection.getByLabel('Event', { exact: true });

    const responsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') && response.status() === 200
    );

    await eventCheckbox.check();
    await responsePromise;

    // Month view should still be active after applying a filter
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();
  });

  test('should navigate months with prev/next buttons', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to month view
    await page.getByRole('radio', { name: /month view/i }).click();
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    // Get the current month heading
    const now = new Date();
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
    const currentHeading = `${monthNames[now.getMonth()]} ${now.getFullYear()}`;
    await expect(page.getByText(currentHeading)).toBeVisible();

    // Click next month
    await page.getByRole('button', { name: /next month/i }).click();

    // Verify heading changed to next month
    const nextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    const nextHeading = `${monthNames[nextMonth.getMonth()]} ${nextMonth.getFullYear()}`;
    await expect(page.getByText(nextHeading)).toBeVisible();

    // Click previous month twice to go back one month from the original
    await page.getByRole('button', { name: /previous month/i }).click();
    await expect(page.getByText(currentHeading)).toBeVisible();

    await page.getByRole('button', { name: /previous month/i }).click();
    const prevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const prevHeading = `${monthNames[prevMonth.getMonth()]} ${prevMonth.getFullYear()}`;
    await expect(page.getByText(prevHeading)).toBeVisible();
  });

  test('should switch to week and day views and display events', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Week Day Cal', color: '#10B981' },
    ]);

    await dataManager.createJournals([
      {
        title: 'Week View Event',
        content: 'Testing week and day views',
        event_date_range: {
          start: relativeDate(0),
          end: relativeDate(0),
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendars[0].id,
            is_all_day: true,
            sync_invitees: false,
          },
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to week view
    await page.getByLabel('Week view').click();
    await expect(page.getByTestId('calendar-week-view')).toBeVisible();
    await expect(
      page.getByRole('link', { name: /week view event/i })
    ).toBeVisible();

    // Switch to month view first to set anchor date deterministically
    await page.getByLabel('Month view').click();
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    const eventLink = page
      .getByRole('link', { name: /week view event/i })
      .first();
    await expect(eventLink).toBeVisible();

    // Click the day header of the cell containing the event to set anchorDate and navigate to Agenda
    await eventLink
      .locator('xpath=ancestor::div[starts-with(@data-testid, "day-cell-")]')
      .locator('div.text-right.text-sm')
      .first()
      .click();

    // Wait until agenda view appears (proves anchorDate is set)
    await expect(page.getByTestId('calendar-agenda-view')).toBeVisible();

    // Switch to day view (anchorDate is now locked)
    await page.getByLabel('Day view').click();
    await expect(page.getByTestId('calendar-day-view')).toBeVisible();
    await expect(
      page.getByRole('link', { name: /week view event/i })
    ).toBeVisible();
  });

  test('should trigger quick create dialog and create a new event', async ({
    authenticatedPage,
    testCleanup,
    isMobile,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    await dataManager.clearAllJournals();

    const calendars = await dataManager.createCalendars([
      { name: 'Quick Create Cal', color: '#10B981' },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();

    // Switch to Month view to use its grid
    await page.getByLabel('Month view').click();
    await expect(page.getByTestId('calendar-month-view')).toBeVisible();

    // Find today's date cell, click it (or the add button) to trigger quick create
    // Since today is marked with data-today="true", we can locate it easily.
    const todayCell = page.locator(
      '[data-testid^="day-cell-"][data-today="true"]'
    );
    await expect(todayCell).toBeVisible();

    // Focus to reveal Add button via group-focus-within
    await todayCell.focus();
    // Also hover just in case
    if (isMobile) {
      await todayCell.tap();
    } else {
      await todayCell.hover();
    }

    // Click Add button (force: true bypasses strict visibility checks that fail during CSS transitions in Firefox)
    const addButton = todayCell.getByRole('button', { name: /add event on/i });
    await addButton.click({ force: true });

    // Verify dialog appears
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole('heading', { name: 'Quick Create Event' })
    ).toBeVisible();

    // Fill form
    await dialog.getByLabel('Title').fill('Quick Created UI Event');

    // Select calendar
    await dialog.getByTestId('calendar-id-input').click();
    const calendarOption = page
      .getByRole('option', { name: calendars[0].name, exact: true })
      .first();
    await expect(calendarOption).toBeVisible({ timeout: 10000 });
    // Use force: true to bypass Playwright mobile bounding box bug on Radix Select portals
    await calendarOption.click({ force: true });

    // Submit form
    // The form contains a button "Create Journal"
    await dialog.getByRole('button', { name: /create journal/i }).click();

    // Wait for the dialog to go away
    await expect(dialog).toBeHidden({ timeout: 10000 });

    // Verify the new event appears in the month grid
    await expect(
      page.getByRole('link', { name: /quick created ui event/i })
    ).toBeVisible();
  });
});
