/**
 * E2E tests for the Snipe-IT integration OAuth flow.
 *
 * Stub API responses to verify the connect and disconnect UI interactions
 * and status updates without requiring a real Snipe-IT instance.
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
 * Helper to set up common routes needed for the integrations page.
 */
async function setupBaseRoutes(
  page: import('@playwright/test').Page,
  snipeitStatus: 'disconnected' | 'connected' = 'disconnected'
) {
  // Health
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

  // Integrations list
  await page.route('**/api/integrations', route => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/integrations') {
      return route.fallback();
    }

    return route.fulfill(
      json({
        data: [
          {
            id: 'snipeit',
            type: 'integration',
            attributes: {
              name: 'Snipe-IT',
              status: snipeitStatus,
              capabilities: ['gear_sync', 'maintenance_sync', 'checkout_sync'],
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

  // Sync history stubs
  await page.route('**/api/integrations/*/sync-history**', route =>
    route.fulfill(
      json({
        data: [],
        meta: { total: 0, page: 1, pageSize: 5 },
      })
    )
  );
}

test.describe('Snipe-IT OAuth Flow', () => {
  test('connect button initiates OAuth flow', async ({ authenticatedPage }) => {
    await setupBaseRoutes(authenticatedPage, 'disconnected');

    // Stub the authorize endpoint
    let authorizePayload: Record<string, unknown> | null = null;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/oauth/authorize',
      async route => {
        if (route.request().method() === 'POST') {
          authorizePayload = route.request().postDataJSON();
          return route.fulfill(
            json({
              authorization_url:
                'https://snipeit.example.com/oauth/authorize?client_id=test-client-id&response_type=code&state=test-state',
              state: 'test-state',
            })
          );
        }
        return route.fallback();
      }
    );

    // Mock navigation so we don't actually leave the app
    await authenticatedPage.route(
      'https://snipeit.example.com/oauth/authorize**',
      route => route.fulfill(json({ message: 'Redirected to Snipe-IT' }))
    );

    await authenticatedPage.goto('/integrations');

    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();

    const connectButton = snipeitPanel.getByRole('button', {
      name: /connect/i,
    });
    await expect(connectButton).toBeVisible();

    // The connect button opens a redirect which our mock catches
    await connectButton.click();

    // Verify authorize endpoint was called
    await expect(async () => {
      expect(authorizePayload).not.toBeNull();
      expect(authorizePayload?.redirect_url).toContain('/integrations');
    }).toPass({ timeout: 5000 });

    // Verify Playwright navigated to the authorization URL
    await expect(authenticatedPage).toHaveURL(
      /snipeit\.example\.com\/oauth\/authorize/
    );
  });

  test('disconnect button sends DELETE and updates status', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage, 'connected');

    let deleteCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/oauth/disconnect',
      async route => {
        if (route.request().method() === 'DELETE') {
          deleteCalled = true;
          // Change the mocked integration list to disconnected after DELETE
          await setupBaseRoutes(authenticatedPage, 'disconnected');
          return route.fulfill(
            json({
              success: true,
              message: 'Snipe-IT disconnected successfully',
            })
          );
        }
        return route.fallback();
      }
    );

    await authenticatedPage.goto('/integrations');

    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();

    // Verify it starts as connected
    await expect(snipeitPanel).toContainText('Connected');

    const disconnectButton = snipeitPanel.getByRole('button', {
      name: /disconnect/i,
    });
    await expect(disconnectButton).toBeVisible();

    // Initiate disconnect
    await disconnectButton.click();

    // Verify delete was called and UI updates
    await expect(async () => {
      expect(deleteCalled).toBe(true);
      await expect(snipeitPanel).toContainText('Disconnected');
    }).toPass({ timeout: 5000 });
  });

  test('snipeit panel shows Connected status when authenticated', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage, 'connected');

    await authenticatedPage.goto('/integrations');

    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();
    await expect(snipeitPanel).toContainText('Connected');

    // Disconnect button should be visible when connected
    const disconnectButton = snipeitPanel.getByRole('button', {
      name: /disconnect/i,
    });
    await expect(disconnectButton).toBeVisible();
  });
});
