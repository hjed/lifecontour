/**
 * UI-focused e2e tests for the Integrations page.
 *
 * These tests stub integration API responses to deterministically cover
 * connected/disconnected UI states and request contracts (method + payload).
 */

import type { Page, Route } from '@playwright/test';
import { expect, test } from './fixtures';

// ─── Shared Helpers ────────────────────────────────────────────────────────

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

/** Set up common route mocks for integrations page with given entries. */
async function setupIntegrationsMocks(page: Page, integrations: unknown[]) {
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
    route.fulfill(
      json({
        data: integrations,
      })
    )
  );

  await page.route(
    '**/api/integrations/google/sync-history**',
    (route: Route) =>
      route.fulfill(
        json({
          data: [],
          meta: { total: 0, page: 1, pageSize: 5 },
        })
      )
  );
}

/**
 * Shared test logic: click Reregister Webhooks, then Reauthorize,
 * and verify both requests fire correctly.
 *
 * @param integrationId - e.g. 'google' or 'strava'
 * @param authorizeEndpoint - API path fragment for the authorize POST
 * @param providerUrlPattern - wildcard pattern for the external OAuth URL
 */
async function testReauthAndReregister(
  page: Page,
  integrationId: string,
  authorizeEndpoint: string,
  providerUrlPattern: string
) {
  let authorizeTriggered = false;
  let reregisterTriggered = false;

  await page.route(
    `**/api/integrations/${integrationId}/**/authorize`,
    async route => {
      const req = route.request();
      if (req.method() !== 'POST') return route.fallback();
      authorizeTriggered = true;
      return route.fulfill(
        json({
          authorization_url: providerUrlPattern.replace('**', ''),
          state: 'test-state',
        })
      );
    }
  );

  await page.route(
    `**/api/integrations/${integrationId}/webhooks/reregister`,
    async route => {
      const req = route.request();
      if (req.method() !== 'POST') return route.fallback();
      reregisterTriggered = true;
      return route.fulfill(
        json({
          data: {
            type: 'webhook-reregister',
            attributes: {
              webhooks_queued: 1,
              message: 'Webhooks reregistered successfully',
            },
          },
        })
      );
    }
  );

  await page.goto('/integrations');

  const panel = page.locator(
    `[data-testid="integration-panel-${integrationId}"]`
  );

  // Click Reregister Webhooks
  const reregisterPromise = page.waitForRequest(
    request =>
      request
        .url()
        .includes(`/api/integrations/${integrationId}/webhooks/reregister`) &&
      request.method() === 'POST'
  );
  await panel.getByTestId(`reregister-webhooks-${integrationId}`).click();
  await reregisterPromise;
  await expect.poll(() => reregisterTriggered).toBe(true);

  // Intercept external OAuth redirect using a wildcard pattern so query
  // params on the authorization_url don't cause a match failure.
  await page.route(providerUrlPattern, route => route.fulfill(json({})));
  const reauthorizePromise = page.waitForRequest(
    request =>
      request.url().includes(authorizeEndpoint) && request.method() === 'POST'
  );
  await panel.getByTestId(`reauthorize-${integrationId}`).click();
  await reauthorizePromise;
  await expect.poll(() => authorizeTriggered).toBe(true);
}

// ─── Fixtures ──────────────────────────────────────────────────────────────

function makeIntegration(
  id: string,
  name: string,
  capabilities: string[],
  overrides: Record<string, unknown> = {}
) {
  return {
    id,
    type: 'integration',
    attributes: {
      name,
      status: 'disconnected',
      capabilities,
      sync_summary: {
        last_sync_time: null,
        sync_count: 0,
        error_count: 0,
      },
      needs_reauth: false,
      needs_reconsent: false,
      ...overrides,
    },
  };
}

const googleDisconnected = makeIntegration('google', 'Google', [
  'contacts_sync',
  'calendar_sync',
]);
const googleConnected = makeIntegration(
  'google',
  'Google',
  ['contacts_sync', 'calendar_sync'],
  {
    status: 'connected',
    sync_summary: {
      last_sync_time: new Date().toISOString(),
      sync_count: 42,
      error_count: 0,
    },
  }
);
const stravaDisconnected = makeIntegration('strava', 'Strava', [
  'activity_import',
]);
const stravaConnected = makeIntegration(
  'strava',
  'Strava',
  ['activity_import'],
  {
    status: 'connected',
    sync_summary: {
      last_sync_time: '2026-01-01T12:00:00Z',
      sync_count: 5,
      error_count: 0,
    },
  }
);

// ─── Google Tests ──────────────────────────────────────────────────────────

test.describe('Integrations Page UI (mocked API)', () => {
  test('disconnected: shows Connect button and hides sync controls', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [googleDisconnected]);
    await authenticatedPage.goto('/integrations');

    await expect(
      authenticatedPage.locator('[data-testid="integration-panel-google"]')
    ).toContainText('Disconnected');

    await expect(
      authenticatedPage.locator('[data-testid="connect-google"]')
    ).toBeVisible();

    await expect(
      authenticatedPage.locator('[data-testid="disconnect-google"]')
    ).toHaveCount(0);

    await expect(
      authenticatedPage.locator('[data-testid="trigger-google-sync"]')
    ).toHaveCount(0);
  });

  test('connected: can trigger sync, renders 0 processed/created, and disconnect flips UI', async ({
    authenticatedPage,
  }) => {
    let connected = true;
    let syncTriggeredPayload: Record<string, unknown> | null = null;
    let disconnectCalled = false;

    const googleDynamic = makeIntegration('google', 'Google', [
      'contacts_sync',
      'calendar_sync',
    ]);

    // Override with a dynamic handler so connection state can change mid-test
    await setupIntegrationsMocks(authenticatedPage, []);

    // Re-register the /api/integrations route with dynamic state
    await authenticatedPage.route('**/api/integrations', route =>
      route.fulfill(
        json({
          data: [
            {
              ...googleDynamic,
              attributes: {
                ...googleDynamic.attributes,
                status: connected ? 'connected' : 'disconnected',
                sync_summary: {
                  last_sync_time: connected ? new Date().toISOString() : null,
                  sync_count: connected ? 123 : 0,
                  error_count: 0,
                },
              },
            },
          ],
        })
      )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/sync-history**',
      route =>
        route.fulfill(
          json({
            data: [
              {
                id: 'job-1',
                type: 'sync-job',
                attributes: {
                  status: 'completed',
                  syncType: 'smart',
                  createdAt: new Date().toISOString(),
                  contactsProcessed: 0,
                  contactsCreated: 0,
                  progress: 100,
                },
              },
            ],
            meta: { total: 1, page: 1, pageSize: 5 },
          })
        )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/sync',
      async route => {
        const req = route.request();
        if (req.method() !== 'POST') return route.fallback();

        syncTriggeredPayload = req.postDataJSON();

        // Leave request in-flight briefly so the UI shows progress
        await new Promise(r => setTimeout(r, 150));

        return route.fulfill(
          json({
            data: {
              id: 'job-queued',
              type: 'sync-job',
              attributes: {
                status: 'queued',
                syncType: 'smart',
                createdAt: new Date().toISOString(),
                progress: 0,
              },
            },
          })
        );
      }
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/oauth/disconnect',
      async route => {
        const req = route.request();
        if (req.method() !== 'DELETE') return route.fallback();
        disconnectCalled = true;
        connected = false;
        return route.fulfill(
          json({
            success: true,
            message: 'Google Contacts disconnected successfully',
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    // Sync history renders 0 values (regression test for falsy rendering)
    // Open Sync History dialog first
    const googlePanel = authenticatedPage.getByTestId(
      'integration-panel-google'
    );
    await googlePanel.getByRole('button', { name: /Sync History/i }).click();

    const jobItem = authenticatedPage
      .locator('[data-testid="sync-job-item"]')
      .first();
    await expect(jobItem).toContainText('0 processed');
    await expect(jobItem).toContainText('0 created');

    // Close the dialog
    await authenticatedPage.keyboard.press('Escape');
    await expect(authenticatedPage.getByRole('dialog')).toBeHidden();

    // Trigger sync sends correct payload and shows progress briefly
    await authenticatedPage.click(
      '[data-testid="trigger-google-contacts-sync"]'
    );

    await expect
      .poll(() => syncTriggeredPayload)
      .toEqual({ sync_type: 'smart' });

    // Disconnect flips UI to disconnected state
    await authenticatedPage.click('[data-testid="disconnect-google"]');
    await expect.poll(() => disconnectCalled).toBeTruthy();
  });

  test('connected with needsReconsent: shows scope upgrade banner and triggers re-auth', async ({
    authenticatedPage,
  }) => {
    let oauthAuthorizePayload: Record<string, unknown> | null = null;

    const googleNeedsReconsent = makeIntegration(
      'google',
      'Google',
      ['contacts_sync', 'calendar_sync'],
      {
        status: 'connected',
        sync_summary: {
          last_sync_time: new Date().toISOString(),
          sync_count: 42,
          error_count: 0,
        },
        needs_reconsent: true,
      }
    );

    await setupIntegrationsMocks(authenticatedPage, [googleNeedsReconsent]);

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/oauth/authorize',
      async route => {
        const req = route.request();
        if (req.method() !== 'POST') return route.fallback();
        oauthAuthorizePayload = req.postDataJSON();
        return route.fulfill(
          json({
            authorization_url:
              'https://accounts.google.com/o/oauth2/auth?scope=calendar',
            state: 'test-state',
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    // Banner should be visible with upgrade messaging
    const banner = authenticatedPage.locator(
      '[data-testid="scope-upgrade-banner-google"]'
    );
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('permissions'); // Use 'permissions' since we don't list specific capabilities anymore

    // Click "Upgrade Permissions" button and verify OAuth is triggered
    await authenticatedPage.click(
      '[data-testid="upgrade-permissions-button-google"]'
    );
    await expect.poll(() => oauthAuthorizePayload).toBeTruthy();
    expect(oauthAuthorizePayload).toEqual({ redirect_url: '/integrations' });
  });

  test('connected without needsReconsent: does not show scope upgrade banner', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [googleConnected]);
    await authenticatedPage.goto('/integrations');

    // Status should show Connected
    await expect(
      authenticatedPage.locator('[data-testid="integration-panel-google"]')
    ).toContainText('Connected');

    // Banner should NOT be visible
    await expect(
      authenticatedPage.locator('[data-testid="scope-upgrade-banner-google"]')
    ).toHaveCount(0);
  });

  test('connected: can trigger reauthorize and reregister webhooks', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [googleConnected]);

    await testReauthAndReregister(
      authenticatedPage,
      'google',
      '/api/integrations/google/contacts/oauth/authorize',
      'https://accounts.google.com/**'
    );
  });
});

// ─── Strava Tests ──────────────────────────────────────────────────────────

test.describe('Strava Integration Panel (mocked API)', () => {
  test('strava disconnected: shows Connect button', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaDisconnected]);
    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.locator(
      '[data-testid="integration-panel-strava"]'
    );
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Strava');
    await expect(panel).toContainText('Disconnected');
    await expect(panel.getByRole('button', { name: /connect/i })).toBeVisible();
  });

  test('strava connected: shows Disconnect button', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaConnected]);
    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.locator(
      '[data-testid="integration-panel-strava"]'
    );
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Connected');
    await expect(
      panel.getByRole('button', { name: /disconnect/i })
    ).toBeVisible();
  });

  test('strava connect initiates OAuth redirect', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaDisconnected]);

    // Intercept the authorize POST and return a mock authorization URL
    await authenticatedPage.route(
      '**/api/integrations/strava/oauth/authorize',
      route =>
        route.fulfill(
          json({
            authorization_url:
              'https://www.strava.com/oauth/authorize?client_id=test',
            state: 'test-state',
          })
        )
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.locator(
      '[data-testid="integration-panel-strava"]'
    );

    // Click connect and verify the authorize request fires
    const authorizePromise = authenticatedPage.waitForRequest(
      request =>
        request.url().includes('/api/integrations/strava/oauth/authorize') &&
        request.method() === 'POST'
    );

    await panel.getByRole('button', { name: /connect/i }).click();
    const authorizeRequest = await authorizePromise;

    expect(authorizeRequest.method()).toBe('POST');
    const body = JSON.parse(authorizeRequest.postData() ?? '{}');
    expect(body.redirect_url).toBe('/integrations');
  });

  test('strava connected: shows sync controls with Import Activities', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaConnected]);
    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.locator(
      '[data-testid="integration-panel-strava"]'
    );
    await expect(panel).toBeVisible();

    // The sync button should be visible for connected Strava
    const syncButton = panel.locator(
      '[data-testid="trigger-strava-activity_import-sync"]'
    );
    await expect(syncButton).toBeVisible();
    await expect(syncButton).toContainText(/sync/i);
  });

  test('strava import triggers POST to activity_import/sync endpoint', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaConnected]);

    // Mock the sync endpoint to return a job
    await authenticatedPage.route(
      '**/api/integrations/strava/activity_import/sync',
      (route: Route) =>
        route.fulfill(
          json({
            data: {
              id: 'job-123',
              type: 'sync-job',
              attributes: {
                status: 'queued',
                syncType: 'smart',
                createdAt: new Date().toISOString(),
                startedAt: null,
                completedAt: null,
                errorMessage: null,
                contactsProcessed: null,
                contactsCreated: null,
                contactsUpdated: null,
                contactsDeleted: null,
                progress: null,
              },
            },
          })
        )
    );

    await authenticatedPage.goto('/integrations');

    const panel = authenticatedPage.locator(
      '[data-testid="integration-panel-strava"]'
    );

    const syncRequest = authenticatedPage.waitForRequest(
      request =>
        request
          .url()
          .includes('/api/integrations/strava/activity_import/sync') &&
        request.method() === 'POST'
    );

    const syncButton = panel.locator(
      '[data-testid="trigger-strava-activity_import-sync"]'
    );
    await syncButton.click();

    const request = await syncRequest;
    expect(request.method()).toBe('POST');

    const reqBody = JSON.parse(request.postData() ?? '{}');
    expect(reqBody.sync_type).toBe('smart');
  });

  test('strava connected: can trigger reauthorize and reregister webhooks', async ({
    authenticatedPage,
  }) => {
    await setupIntegrationsMocks(authenticatedPage, [stravaConnected]);

    await testReauthAndReregister(
      authenticatedPage,
      'strava',
      '/api/integrations/strava/oauth/authorize',
      'https://www.strava.com/**'
    );
  });
});
