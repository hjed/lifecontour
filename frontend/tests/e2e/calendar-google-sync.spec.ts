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

const googleStatusDisconnected = {
  data: {
    id: 'google',
    type: 'integration-status',
    attributes: {
      connected: false,
      lastSync: null,
      syncCount: 0,
      status: 'disconnected',
      needsReconsent: false,
    },
  },
};

const googleStatusNeedsReconsent = {
  data: {
    id: 'google',
    type: 'integration-status',
    attributes: {
      connected: true,
      lastSync: new Date().toISOString(),
      syncCount: 10,
      status: 'active',
      needsReconsent: true,
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
      },
    },
    {
      id: 'work@group.v.calendar.google.com',
      type: 'google-calendar',
      attributes: {
        summary: 'Work Calendar',
        backgroundColor: '#7986cb',
        primary: false,
      },
    },
  ],
};

test.describe('Calendar Google Sync Settings', () => {
  test('sync toggle is enabled when Google is connected with calendar scopes', async ({
    authenticatedPage: page,
  }) => {
    // Mock Google status as connected
    await page.route(
      '**/api/integrations/google/contacts/status',
      route => route.fulfill(json(googleStatusConnected))
    );
    await page.route(
      '**/api/integrations/google/calendars',
      route => route.fulfill(json(googleCalendars))
    );

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    // Open Create Calendar dialog
    await page.getByRole('button', { name: 'Add Calendar' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Sync toggle should be enabled
    const toggle = page.getByTestId('google-sync-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toBeDisabled();
  });

  test('sync toggle is disabled when Google is not connected', async ({
    authenticatedPage: page,
  }) => {
    // Mock Google status as disconnected
    await page.route(
      '**/api/integrations/google/contacts/status',
      route => route.fulfill(json(googleStatusDisconnected))
    );

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Add Calendar' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Sync toggle should be disabled
    const toggle = page.getByTestId('google-sync-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeDisabled();
  });

  test('sync toggle is disabled when needsReconsent is true', async ({
    authenticatedPage: page,
  }) => {
    await page.route(
      '**/api/integrations/google/contacts/status',
      route => route.fulfill(json(googleStatusNeedsReconsent))
    );

    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Add Calendar' }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    const toggle = page.getByTestId('google-sync-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toBeDisabled();
  });

  test('enabling sync shows Google Calendar dropdown and submits with google_calendar_id', async ({
    authenticatedPage: page,
  }) => {
    let createPayload: any = null;

    await page.route(
      '**/api/integrations/google/contacts/status',
      route => route.fulfill(json(googleStatusConnected))
    );
    await page.route(
      '**/api/integrations/google/calendars',
      route => route.fulfill(json(googleCalendars))
    );
    // Intercept calendar creation to capture payload
    await page.route('**/api/calendars', async route => {
      if (route.request().method() === 'POST') {
        createPayload = JSON.parse(
          (await route.request().postData()) || '{}'
        );
        await route.fulfill(
          json({
            data: {
              id: 'new-calendar-id',
              type: 'calendars',
              attributes: createPayload.data?.attributes || {},
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
      .poll(() => createPayload !== null, { timeout: 5000 })
      .toBeTruthy();
    expect(createPayload.data.attributes.is_synced_to_google).toBe(true);
    expect(createPayload.data.attributes.google_calendar_id).toBe(
      'work@group.v.calendar.google.com'
    );
  });
});
