import { test, expect } from './fixtures';

/**
 * E2E tests for calendar view sync indicators and triggers.
 *
 * Requirements:
 * - Event pills should display sync status (Cloud icon) when synced.
 * - Event pills should display review status (Needs Review badge) when conflicted.
 * - The Integrations Page should contain a manual Calendar sync trigger.
 */

const json = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(body),
});

test.describe('Journals Calendar Sync Features', () => {
  // Note: calendar event pill sync-indicator / needs-review-badge rendering is
  // unit-tested in CalendarEventPill.test.tsx. This file keeps only the
  // integrations-page sync trigger flow.

  test('trigger calendar sync from integrations page', async ({
    authenticatedPage: page,
  }) => {
    const googleRegistryResponse = {
      data: [
        {
          id: 'google',
          type: 'integration',
          attributes: {
            name: 'Google',
            status: 'connected',
            capabilities: ['contacts_sync', 'calendar_sync'],
            needs_reauth: false,
            needs_reconsent: false,
            sync_summary: {
              last_sync_time: new Date().toISOString(),
              sync_count: 10,
              error_count: 0,
            },
          },
        },
      ],
    };

    // Route for integration registry
    await page.route('**/api/integrations', route =>
      route.fulfill(json(googleRegistryResponse))
    );

    // Route for calendar sync endpoint
    let calendarSyncRequested = false;
    await page.route(
      '**/api/integrations/google/calendar/sync',
      async route => {
        if (route.request().method() === 'POST') {
          calendarSyncRequested = true;
          const body = JSON.parse((await route.request().postData()) || '{}');
          expect(body.sync_type).toBe('smart');

          await route.fulfill(
            json({
              data: {
                id: 'test-sync-job-id',
                type: 'sync-job',
                attributes: {
                  status: 'pending',
                  syncType: 'smart',
                  createdAt: new Date().toISOString(),
                },
              },
            })
          );
        } else {
          await route.continue();
        }
      }
    );

    // We also need to mock the sync history/health returning empty so the UI loads
    await page.route('**/api/integrations/health', route =>
      route.fulfill(
        json({
          data: {
            attributes: {
              overall: 'healthy',
              redis: { status: 'healthy' },
              worker: { status: 'healthy' },
            },
          },
        })
      )
    );
    await page.route('**/api/integrations/google/sync-history**', route =>
      route.fulfill(json({ data: [] }))
    );

    // Navigate to integrations page
    await page.goto('/integrations');
    await expect(
      page.getByRole('heading', { name: 'Integrations' })
    ).toBeVisible();

    // Trigger calendar sync
    const syncCalendarButton = page.getByTestId('trigger-google-calendar-sync');
    await expect(syncCalendarButton).toBeVisible();
    await syncCalendarButton.click();

    // Verify sync was requested
    await expect.poll(() => calendarSyncRequested).toBeTruthy();
  });
});
