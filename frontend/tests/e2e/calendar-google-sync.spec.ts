import { test, expect } from './fixtures';

/**
 * E2E tests for calendar creation/editing with Google sync selection.
 *
 * These tests mock the backend APIs to verify the CalendarSettingsDialog
 * behaviour when Google is connected, disconnected, or needs reconsent.
 */

const json = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

const googleStatusConnected = {
  data: {
    id: 'google',
    type: 'integration-status',
    attributes: {
      connected: true,
      lastSync: new Date().toISOString(),
      syncCount: 10,
      status: 'active',
      needsReconsent: false,
    },
  },
};

const googleCalendars = {
  data: [
    {
      id: 'primary@gmail.com',
      type: 'google-calendar',
      attributes: {
        summary: 'My Calendar',
        description: 'Main calendar',
        backgroundColor: '#4285f4',
        primary: true,
        accessRole: 'owner',
      },
    },
    {
      id: 'work@group.v.calendar.google.com',
      type: 'google-calendar',
      attributes: {
        summary: 'Work Calendar',
        backgroundColor: '#7986cb',
        primary: false,
        accessRole: 'writer',
      },
    },
    {
      id: 'shared@example.com',
      type: 'google-calendar',
      attributes: {
        summary: 'Shared Calendar',
        backgroundColor: '#33b679',
        primary: false,
        accessRole: 'reader',
      },
    },
  ],
};

test.describe('Calendar Google Sync Settings', () => {
  // Note: google-sync-toggle enabled/disabled state (connected / disconnected /
  // needsReconsent) is unit-tested in CalendarSettingsDialog.test.tsx. This file
  // keeps only the real submit-payload contract that the component test cannot cover.

  test('enabling sync shows Google Calendar dropdown and submits with google_calendar_id', async ({
    authenticatedPage: page,
  }) => {
    let createPayload: {
      data: {
        attributes: {
          is_synced_to_google: boolean;
          google_calendar_id: string;
        };
      };
    } | null = null;

    await page.route('**/api/integrations/google/contacts/status', route =>
      route.fulfill(json(googleStatusConnected))
    );
    await page.route('**/api/integrations/google/calendars', route =>
      route.fulfill(json(googleCalendars))
    );
    // Intercept calendar creation to capture payload
    await page.route('**/api/calendars', async route => {
      if (route.request().method() === 'POST') {
        createPayload = JSON.parse((await route.request().postData()) || '{}');
        await route.fulfill(
          json({
            data: {
              id: 'new-calendar-id',
              type: 'calendars',
              attributes: createPayload?.data?.attributes || {},
            },
          })
        );
      } else {
        // GET /api/calendars - return empty list
        await route.fulfill(json({ data: [] }));
      }
    });

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Add Calendar' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Fill in calendar name
    await page.getByLabel(/name/i).fill('My Synced Calendar');

    // Enable Google sync
    await page.getByTestId('google-sync-toggle').click();

    // Google Calendar dropdown should appear
    const selectTrigger = page.getByTestId('google-calendar-select');
    await expect(selectTrigger).toBeVisible();

    // Open dropdown and select a calendar
    await selectTrigger.click();
    await page.getByRole('option', { name: 'Work Calendar' }).click();

    // Submit the form
    await page.getByRole('button', { name: /save changes/i }).click();

    // Verify the payload includes google_calendar_id and is_synced_to_google
    await expect
      .poll(() => createPayload !== null, { timeout: 10000 })
      .toBeTruthy();
    expect(createPayload!.data.attributes.is_synced_to_google).toBe(true);
    expect(createPayload!.data.attributes.google_calendar_id).toBe(
      'work@group.v.calendar.google.com'
    );
  });

  test('selecting a read-only Google calendar warns that changes will not be sent back', async ({
    authenticatedPage: page,
  }) => {
    await page.route('**/api/integrations/google/contacts/status', route =>
      route.fulfill(json(googleStatusConnected))
    );
    await page.route('**/api/integrations/google/calendars', route =>
      route.fulfill(json(googleCalendars))
    );
    await page.route('**/api/calendars', route =>
      route.fulfill(json({ data: [] }))
    );

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Add Calendar' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    await page.getByTestId('google-sync-toggle').click();
    const selectTrigger = page.getByTestId('google-calendar-select');
    await expect(selectTrigger).toBeVisible();

    // A writable calendar carries no warning...
    await selectTrigger.click();
    await page.getByRole('option', { name: 'Work Calendar' }).click();
    await expect(page.getByTestId('read-only-calendar-warning')).toBeHidden();

    // ...while one shared read-only says so before the calendar is saved.
    await selectTrigger.click();
    await page.getByRole('option', { name: 'Shared Calendar' }).click();
    await expect(page.getByTestId('read-only-calendar-warning')).toContainText(
      /read-only access/i
    );
  });
});
