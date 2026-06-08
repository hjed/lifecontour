/**
 * E2E tests for the Immich integration settings modal.
 *
 * These tests stub integration API responses to deterministically verify
 * the Immich settings modal opens and submits credentials cleanly.
 */

import { expect, test } from './fixtures';

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

/**
 * Shared API route stubs that every test in this file needs.
 * Sets up: health, integration list (with immich), sync history.
 */
async function setupBaseRoutes(page: import('@playwright/test').Page) {
  // Health endpoint
  await page.route('**/api/integrations/health', route =>
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

  // Integration list — includes immich as disconnected
  await page.route('**/api/integrations', route => {
    // Only handle exact /api/integrations, not sub-paths
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/integrations') {
      return route.fallback();
    }

    return route.fulfill(
      json({
        data: [
          {
            id: 'immich',
            type: 'integration',
            attributes: {
              name: 'Immich',
              status: 'disconnected',
              capabilities: ['contacts_sync', 'album_sync'],
              sync_summary: {
                last_sync_time: null,
                sync_count: 0,
                error_count: 0,
              },
              needs_reauth: false,
              needs_reconsent: false,
            },
          },
        ],
      })
    );
  });

  // Sync history stubs for all integrations
  await page.route('**/api/integrations/*/sync-history**', route =>
    route.fulfill(
      json({
        data: [],
        meta: { total: 0, page: 1, pageSize: 5 },
      })
    )
  );
}

// Note: panel visibility and "settings modal opens + shows form" are covered
// generically in provider-settings.spec.ts. Pure form rendering / validation is
// unit-tested in ImmichSettings.test.tsx. The tests here cover the real connect
// and sync request contracts.
test.describe('Immich Integration Settings', () => {
  test('can connect to Immich', async ({ authenticatedPage }) => {
    await setupBaseRoutes(authenticatedPage);

    // Mock successful connect
    await authenticatedPage.route(
      '**/api/integrations/immich/connect',
      route => {
        if (route.request().method() !== 'POST') return route.fallback();
        return route.fulfill(
          json({
            status: 'success',
            message: 'Connected to Immich successfully',
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    // Open settings modal
    const immichPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-immich"]'
    );
    await immichPanel.getByRole('button', { name: /settings/i }).click();

    // Fill form
    const form = authenticatedPage.locator(
      '[data-testid="immich-settings-form"]'
    );
    await form
      .locator('[data-testid="immich-server-url-input"]')
      .fill('https://immich.example.com');
    await form
      .locator('[data-testid="immich-api-key-input"]')
      .fill('test-api-key');

    // Stub the integrations endpoint to return connected on subsequent calls
    let getIntegrationsCallCount = 0;
    await authenticatedPage.route('**/api/integrations', async route => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/integrations') {
        return route.fallback();
      }

      getIntegrationsCallCount++;

      return route.fulfill(
        json({
          data: [
            {
              id: 'immich',
              type: 'integration',
              attributes: {
                name: 'Immich',
                status:
                  getIntegrationsCallCount > 1 ? 'connected' : 'disconnected',
                capabilities: ['contacts_sync', 'album_sync'],
                sync_summary: {
                  last_sync_time: null,
                  sync_count: 0,
                  error_count: 0,
                },
                needs_reauth: false,
                needs_reconsent: false,
              },
            },
          ],
        })
      );
    });

    // Click connect
    await form.locator('[data-testid="immich-connect-button"]').click();

    // Verify toast notification
    await expect(
      authenticatedPage.getByText('Connected to Immich successfully')
    ).toBeVisible();

    // Wait for the modal UI to update or verify it resets
    await expect(
      form.locator('[data-testid="immich-server-url-input"]')
    ).toHaveValue('');
  });
});

test.describe('Immich Sync Controls', () => {
  /**
   * Setup routes for a connected Immich integration.
   */
  async function setupConnectedRoutes(page: import('@playwright/test').Page) {
    // Health endpoint
    await page.route('**/api/integrations/health', route =>
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

    // Integration list — immich as connected
    await page.route('**/api/integrations', route => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/integrations') {
        return route.fallback();
      }

      return route.fulfill(
        json({
          data: [
            {
              id: 'immich',
              type: 'integration',
              attributes: {
                name: 'Immich',
                status: 'connected',
                capabilities: ['contacts_sync', 'album_sync'],
                sync_summary: {
                  last_sync_time: '2026-01-15T10:30:00Z',
                  sync_count: 5,
                  error_count: 0,
                },
                needs_reauth: false,
                needs_reconsent: false,
              },
            },
          ],
        })
      );
    });

    // Sync history
    await page.route('**/api/integrations/*/sync-history**', route =>
      route.fulfill(
        json({
          data: [],
          meta: { total: 0, page: 1, pageSize: 5 },
        })
      )
    );
  }

  // Note: sync-control button visibility by connection state is unit-tested in
  // IntegrationPanel.test.tsx. This test covers the real sync POST contract.
  test('clicking contacts sync button triggers API call', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    // Mock the sync trigger endpoint
    let syncRequestReceived = false;
    await authenticatedPage.route(
      '**/api/integrations/immich/contacts/sync',
      route => {
        if (route.request().method() !== 'POST') return route.fallback();
        syncRequestReceived = true;
        return route.fulfill(
          json({
            data: {
              id: 'sync-job-1',
              type: 'sync-job',
              attributes: {
                status: 'queued',
                syncType: 'smart',
                integrationSource: 'immich',
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
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const immichPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-immich"]'
    );
    await expect(immichPanel).toBeVisible();

    // Click the contacts sync button
    const contactsSyncButton = immichPanel.locator(
      '[data-testid="trigger-immich-contacts-sync"]'
    );
    await expect(contactsSyncButton).toBeVisible();
    await contactsSyncButton.click();

    // Verify the sync toast notification appears
    await expect(
      authenticatedPage.getByText(/sync started successfully/i)
    ).toBeVisible();

    // Verify the API was called
    expect(syncRequestReceived).toBe(true);
  });
});
