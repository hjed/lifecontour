/**
 * E2E tests for Integration Actions (webhook re-registration & re-authentication).
 *
 * Tests cover:
 * - Webhook re-registration buttons for Google, Strava, and Snipe-IT
 * - Re-authentication button triggering OAuth redirect
 * - Correct API calls and success/error toasts
 * - Buttons only shown when integration is connected
 */

import type { Page, Route } from '@playwright/test';
import { expect, test } from './fixtures';

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

function jsonError(status: number, detail: string) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify({
      errors: [{ detail }],
    }),
  };
}

/**
 * Helper to set up common route mocks for the integrations page.
 */
async function setupCommonMocks(page: Page, integrations: unknown[]) {
  await page.route('**/api/integrations/health', (route: Route) =>
    route.fulfill(
      json({
        data: {
          id: 'integrations',
          type: 'integration-health',
          attributes: {
            overall: 'healthy',
            lastChecked: new Date().toISOString(),
            redis: { status: 'healthy', latency: 1, lastSeen: null },
            worker: { status: 'healthy', latency: 1, lastSeen: null },
          },
        },
      })
    )
  );

  await page.route('**/api/integrations', (route: Route) =>
    route.fulfill(json({ data: integrations }))
  );

  // Common sync-history and dead-letters mocks
  await page.route('**/api/integrations/*/sync-history**', (route: Route) =>
    route.fulfill(
      json({
        data: [],
        meta: { total: 0, page: 1, pageSize: 5 },
      })
    )
  );

  await page.route('**/api/health/dead-letters**', (route: Route) =>
    route.fulfill(json({ items: [], total: 0, limit: 50, offset: 0 }))
  );

  await page.route('**/api/health/consumer-lag', (route: Route) =>
    route.fulfill(json([]))
  );
}

const googleConnected = {
  id: 'google',
  type: 'integration',
  attributes: {
    name: 'Google',
    status: 'connected',
    capabilities: ['contacts_sync', 'calendar_sync'],
    sync_summary: {
      last_sync_time: '2026-01-01T12:00:00Z',
      sync_count: 42,
      error_count: 0,
    },
    needs_reauth: false,
    needs_reconsent: false,
  },
};

const stravaConnected = {
  id: 'strava',
  type: 'integration',
  attributes: {
    name: 'Strava',
    status: 'connected',
    capabilities: ['activity_import'],
    sync_summary: {
      last_sync_time: '2026-01-01T12:00:00Z',
      sync_count: 5,
      error_count: 0,
    },
    needs_reauth: false,
    needs_reconsent: false,
  },
};

test.describe('Integration Actions - Webhook Re-registration', () => {
  test('Google: re-register webhooks button triggers API call and shows success toast', async ({
    authenticatedPage,
  }) => {
    await setupCommonMocks(authenticatedPage, [googleConnected]);

    let reregisterCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/google/webhooks/reregister',
      async (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        reregisterCalled = true;
        return route.fulfill(
          json({
            data: {
              type: 'webhook-reregister',
              attributes: {
                webhooks_queued: 3,
                message: 'Queued webhook re-registration for 3 calendar(s)',
              },
            },
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.getByTestId('integration-panel-google');
    await expect(panel).toBeVisible();

    // Click the re-register webhooks button
    const reregisterButton = panel.getByTestId('reregister-webhooks-google');
    await expect(reregisterButton).toBeVisible();
    await reregisterButton.click();

    // Verify API was called
    await expect.poll(() => reregisterCalled).toBeTruthy();

    // Verify success toast
    await expect(
      authenticatedPage.locator('[data-sonner-toast]').first()
    ).toContainText(/webhook/i);
  });

  test('Strava: re-register webhooks button triggers API call', async ({
    authenticatedPage,
  }) => {
    await setupCommonMocks(authenticatedPage, [stravaConnected]);

    let reregisterCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/strava/webhooks/reregister',
      async (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        reregisterCalled = true;
        return route.fulfill(
          json({
            data: {
              type: 'webhook-reregister',
              attributes: {
                webhooks_queued: 1,
                message: 'Strava webhook re-registered successfully',
              },
            },
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.getByTestId('integration-panel-strava');
    await expect(panel).toBeVisible();

    const reregisterButton = panel.getByTestId('reregister-webhooks-strava');
    await expect(reregisterButton).toBeVisible();
    await reregisterButton.click();

    await expect.poll(() => reregisterCalled).toBeTruthy();
  });

  // Note: button visibility by connection state (snipeit webhook-URL vs
  // reregister, and hiding webhook/reauth when disconnected) is unit-tested in
  // IntegrationPanel.test.tsx. The tests here cover the real action request
  // contracts (re-register POST, re-auth OAuth) instead.
});

test.describe('Integration Actions - Re-authentication', () => {
  test('Google: re-authenticate button triggers OAuth flow', async ({
    authenticatedPage,
  }) => {
    await setupCommonMocks(authenticatedPage, [googleConnected]);

    let oauthCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/google/contacts/oauth/authorize',
      async (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        oauthCalled = true;
        return route.fulfill(
          json({
            authorization_url:
              'https://accounts.google.com/o/oauth2/auth?scope=test',
            state: 'test-state',
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.getByTestId('integration-panel-google');
    await expect(panel).toBeVisible();

    const reauthButton = panel.getByTestId('reauth-google');
    await expect(reauthButton).toBeVisible();
    await reauthButton.click();

    await expect.poll(() => oauthCalled).toBeTruthy();
  });

  test('Strava: re-authenticate button triggers OAuth flow', async ({
    authenticatedPage,
  }) => {
    await setupCommonMocks(authenticatedPage, [stravaConnected]);

    let oauthCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/strava/oauth/authorize',
      async (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        oauthCalled = true;
        return route.fulfill(
          json({
            authorization_url:
              'https://www.strava.com/oauth/authorize?client_id=test',
            state: 'test-state',
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.getByTestId('integration-panel-strava');
    const reauthButton = panel.getByTestId('reauth-strava');
    await expect(reauthButton).toBeVisible();
    await reauthButton.click();

    await expect.poll(() => oauthCalled).toBeTruthy();
  });

  test('webhook re-registration error shows error toast', async ({
    authenticatedPage,
  }) => {
    await setupCommonMocks(authenticatedPage, [googleConnected]);

    await authenticatedPage.route(
      '**/api/integrations/google/webhooks/reregister',
      async (route: Route) => {
        if (route.request().method() !== 'POST') return route.fallback();
        return route.fulfill(jsonError(404, 'No Google account connected'));
      }
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.getByTestId('integration-panel-google');
    const reregisterButton = panel.getByTestId('reregister-webhooks-google');
    await reregisterButton.click();

    // Verify error toast appears
    await expect(
      authenticatedPage
        .locator('[data-sonner-toast][data-type="error"]')
        .first()
    ).toBeVisible();
  });
});
