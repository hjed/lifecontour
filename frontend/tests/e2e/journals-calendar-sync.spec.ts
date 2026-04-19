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
  test('calendar event pill displays sync indicator and review badge', async ({
    authenticatedPage: page,
  }) => {
    // Generate a test event with both flags set
    const mockJournals = {
      data: [
        {
          id: 'test-event-sync-review',
          type: 'journals',
          attributes: {
            title: 'Synced and Conflicted Event',
            content: 'Test content',
            is_active: true,
            has_pending_reviews: true,
            timezone: 'UTC',
            event_date_range: {
              start: new Date().toISOString(),
              end: new Date(Date.now() + 3600000).toISOString(),
            },
            types: ['event'],
            tags: [],
            contacts: [],
            calendar: {
              id: 'cal-id',
              start_date: new Date().toISOString(),
              end_date: new Date().toISOString(),
              is_all_day: false,
              is_synced_to_google: true,
              calendar_id: null,
            },
          },
        },
      ],
      included: [],
    };

    // Intercept the review queue to return empty so it doesn't crash
    await page.route(
      url => url.pathname === '/api/journals/reviews',
      route => route.fulfill(json({ data: [] }))
    );

    // Intercept the journal feed
    await page.route(
      url => url.pathname === '/api/journals',
      async route => {
        return route.fulfill(json(mockJournals));
      }
    );

    // Navigate to journals page
    await page.goto('/journals');

    // Make sure we are on Month view
    await page.getByRole('radio', { name: 'Month view' }).click();

    // The text 'Synced and Conflicted Event' should appear
    await expect(
      page.getByText('Synced and Conflicted Event').first()
    ).toBeVisible({ timeout: 10000 });

    // Verify indicators
    const syncIndicator = page.getByTestId('sync-indicator').first();
    const reviewBadge = page.getByTestId('needs-review-badge').first();

    await expect(syncIndicator).toBeVisible();
    await expect(reviewBadge).toBeVisible();
  });

  test('trigger calendar sync from integrations page', async ({
    authenticatedPage: page,
  }) => {
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

    // Route for integration status
    await page.route('**/api/integrations/google/contacts/status', route =>
      route.fulfill(json(googleStatusConnected))
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
    await page.route(
      '**/api/integrations/google/contacts/sync-history**',
      route => route.fulfill(json({ data: [] }))
    );

    // Navigate to integrations page
    await page.goto('/integrations');
    await expect(
      page.getByRole('heading', { name: 'Integrations' })
    ).toBeVisible();

    // Trigger calendar sync
    const syncCalendarButton = page.getByTestId('trigger-calendar-sync');
    await expect(syncCalendarButton).toBeVisible();
    await syncCalendarButton.click();

    // Verify sync was requested
    await expect.poll(() => calendarSyncRequested).toBeTruthy();
  });
});
