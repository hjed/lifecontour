/**
 * UI-focused e2e tests for the Integrations page.
 *
 * These tests stub integration API responses to deterministically cover
 * connected/disconnected UI states and request contracts (method + payload).
 */

import { expect, test } from './fixtures';

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

test.describe('Integrations Page UI (mocked API)', () => {
  test('disconnected: shows Connect button and hides sync controls', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route('**/api/integrations/health', route =>
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

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/status',
      route =>
        route.fulfill(
          json({
            data: {
              id: 'google',
              type: 'integration-status',
              attributes: {
                connected: false,
                lastSync: null,
                syncCount: 0,
                status: 'disconnected',
              },
            },
          })
        )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/sync-history**',
      route =>
        route.fulfill(
          json({
            data: [],
            meta: { total: 0, page: 1, pageSize: 5 },
          })
        )
    );

    await authenticatedPage.goto('/integrations');

    await expect(
      authenticatedPage.locator('[data-testid="integration-status"]')
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
    let syncTriggeredPayload: any = null;
    let disconnectCalled = false;

    await authenticatedPage.route('**/api/integrations/health', route =>
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

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/status',
      route =>
        route.fulfill(
          json({
            data: {
              id: 'google',
              type: 'integration-status',
              attributes: {
                connected,
                lastSync: connected ? new Date().toISOString() : null,
                syncCount: connected ? 123 : 0,
                status: connected ? 'active' : 'disconnected',
              },
            },
          })
        )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/sync-history**',
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
    const jobItem = authenticatedPage
      .locator('[data-testid="sync-job-item"]')
      .first();
    await expect(jobItem).toContainText('0 processed');
    await expect(jobItem).toContainText('0 created');

    // Trigger sync sends correct payload and shows progress briefly
    await authenticatedPage.click('[data-testid="trigger-google-sync"]');
    await expect(
      authenticatedPage.locator('[data-testid="sync-progress"]')
    ).toBeVisible();
    await expect
      .poll(() => syncTriggeredPayload)
      .toEqual({ sync_type: 'smart' });
    await expect(
      authenticatedPage.locator('[data-testid="sync-progress"]')
    ).toHaveCount(0);

    // Disconnect flips UI to disconnected state
    await authenticatedPage.click('[data-testid="disconnect-google"]');
    await expect.poll(() => disconnectCalled).toBeTruthy();
    await expect(
      authenticatedPage.locator('[data-testid="connect-google"]')
    ).toBeVisible();
  });

  test('connected with needsReconsent: shows scope upgrade banner and triggers re-auth', async ({
    authenticatedPage,
  }) => {
    let oauthAuthorizePayload: any = null;

    await authenticatedPage.route('**/api/integrations/health', route =>
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

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/status',
      route =>
        route.fulfill(
          json({
            data: {
              id: 'google',
              type: 'integration-status',
              attributes: {
                connected: true,
                lastSync: new Date().toISOString(),
                syncCount: 42,
                status: 'active',
                needsReconsent: true,
              },
            },
          })
        )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/sync-history**',
      route =>
        route.fulfill(
          json({
            data: [],
            meta: { total: 0, page: 1, pageSize: 5 },
          })
        )
    );

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
      '[data-testid="scope-upgrade-banner"]'
    );
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('calendar');

    // Click "Upgrade Permissions" button and verify OAuth is triggered
    await authenticatedPage.click('[data-testid="upgrade-permissions-button"]');
    await expect.poll(() => oauthAuthorizePayload).toBeTruthy();
    expect(oauthAuthorizePayload).toEqual({ redirect_url: '/integrations' });
  });

  test('connected without needsReconsent: does not show scope upgrade banner', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.route('**/api/integrations/health', route =>
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

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/status',
      route =>
        route.fulfill(
          json({
            data: {
              id: 'google',
              type: 'integration-status',
              attributes: {
                connected: true,
                lastSync: new Date().toISOString(),
                syncCount: 42,
                status: 'active',
                needsReconsent: false,
              },
            },
          })
        )
    );

    await authenticatedPage.route(
      '**/api/integrations/google/contacts/sync-history**',
      route =>
        route.fulfill(
          json({
            data: [],
            meta: { total: 0, page: 1, pageSize: 5 },
          })
        )
    );

    await authenticatedPage.goto('/integrations');

    // Status should show Connected
    await expect(
      authenticatedPage.locator('[data-testid="integration-status"]')
    ).toContainText('Connected');

    // Banner should NOT be visible
    await expect(
      authenticatedPage.locator('[data-testid="scope-upgrade-banner"]')
    ).toHaveCount(0);
  });
});
