/**
 * E2E tests for the Snipe-IT integration settings modal.
 *
 * These tests stub integration API responses to deterministically verify
 * the Snipe-IT settings modal opens and submits Base URL cleanly.
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
 * Sets up: health, integration list (with snipeit), sync history.
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

  // Integration list — includes snipeit as disconnected
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
            id: 'google',
            type: 'integration',
            attributes: {
              name: 'Google',
              status: 'connected',
              capabilities: ['contacts_sync', 'calendar_sync'],
              sync_summary: {
                last_sync_time: null,
                sync_count: 0,
                error_count: 0,
              },
              needs_reauth: false,
              needs_reconsent: false,
            },
          },
          {
            id: 'strava',
            type: 'integration',
            attributes: {
              name: 'Strava',
              status: 'disconnected',
              capabilities: ['activity_import'],
              sync_summary: {
                last_sync_time: null,
                sync_count: 0,
                error_count: 0,
              },
              needs_reauth: false,
              needs_reconsent: false,
            },
          },
          {
            id: 'snipeit',
            type: 'integration',
            attributes: {
              name: 'Snipe-IT',
              status: 'disconnected',
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
// generically in provider-settings.spec.ts. Pure form rendering, invalid-URL
// validation, and existing-settings pre-population are unit-tested in
// SnipeItSettings.test.tsx. The tests here cover the real save/connect/disconnect
// request contracts.
test.describe('Snipe-IT Integration Settings', () => {
  test('settings modal submits Base URL cleanly', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);

    // Mock 404 for initial settings fetch (no settings yet)
    await page_mockSnipeItSettingsNotFound(authenticatedPage);

    // Track the PUT request payload
    let savedPayload: Record<string, unknown> | null = null;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/settings',
      async route => {
        if (route.request().method() === 'PUT') {
          savedPayload = route.request().postDataJSON();
          return route.fulfill(
            json({
              data: {
                id: '123',
                type: 'snipeit_settings',
                attributes: {
                  base_url: savedPayload?.base_url,
                  snipeit_user_id: savedPayload?.snipeit_user_id ?? null,
                },
              },
            })
          );
        }
        // GET returns 404 (no settings yet)
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [{ detail: 'No Snipe-IT settings found for this user' }],
          }),
        });
      }
    );

    await authenticatedPage.goto('/integrations');

    // Open settings modal
    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();

    const settingsButton = snipeitPanel.getByRole('button', {
      name: /settings/i,
    });
    await settingsButton.click();

    // Fill in the form
    const baseUrlInput = authenticatedPage.locator(
      '[data-testid="snipeit-base-url-input"]'
    );
    await expect(baseUrlInput).toBeVisible();
    await baseUrlInput.fill('https://snipeit.example.com');

    const userIdInput = authenticatedPage.locator(
      '[data-testid="snipeit-user-id-input"]'
    );
    await userIdInput.fill('42');

    // Submit the form
    const saveButton = authenticatedPage.locator(
      '[data-testid="snipeit-settings-save-button"]'
    );
    await saveButton.click();

    // Verify the PUT request was sent with correct payload
    await expect(async () => {
      expect(savedPayload).not.toBeNull();
      expect(savedPayload?.base_url).toBe('https://snipeit.example.com');
      expect(savedPayload?.snipeit_user_id).toBe('42');
    }).toPass({ timeout: 5000 });
  });

  test('settings modal submits API Key and triggers connect flow', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);
    await page_mockSnipeItSettingsNotFound(authenticatedPage);

    let connectCalled = false;
    let savedConnectPayload: Record<string, unknown> | null = null;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/connect',
      async route => {
        if (route.request().method() === 'POST') {
          connectCalled = true;
          savedConnectPayload = route.request().postDataJSON();
          return route.fulfill(
            json({
              data: {
                id: 'snipeit',
                type: 'integration',
                attributes: {
                  name: 'Snipe-IT',
                  status: 'connected',
                },
              },
            })
          );
        }
        return route.fallback();
      }
    );

    // Mock settings save to succeed
    await authenticatedPage.route(
      '**/api/integrations/snipeit/settings',
      async route => {
        if (route.request().method() === 'PUT') {
          return route.fulfill(
            json({
              data: {
                id: '123',
                type: 'snipeit_settings',
                attributes: {
                  base_url: 'https://snipeit.example.com',
                  snipeit_user_id: '42',
                },
              },
            })
          );
        }
        return route.fallback();
      }
    );

    await authenticatedPage.goto('/integrations');

    // Open settings modal
    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();
    await snipeitPanel.getByRole('button', { name: /settings/i }).click();

    // Fill in the form
    await authenticatedPage
      .locator('[data-testid="snipeit-base-url-input"]')
      .fill('https://snipeit.example.com');
    await authenticatedPage
      .locator('[data-testid="snipeit-user-id-input"]')
      .fill('42');
    await authenticatedPage
      .locator('[data-testid="snipeit-api-key-input"]')
      .fill('super-secret-key');

    // Submit
    await authenticatedPage
      .locator('[data-testid="snipeit-settings-save-button"]')
      .click();

    // Verify connect endpoint was called with API key
    await expect(async () => {
      expect(connectCalled).toBe(true);
      expect(savedConnectPayload).not.toBeNull();
      expect(savedConnectPayload?.api_key).toBe('super-secret-key');
    }).toPass({ timeout: 5000 });
  });

  test('disconnect button sends DELETE and updates status', async ({
    authenticatedPage,
  }) => {
    // Override base routes to make Snipe-IT connected
    await authenticatedPage.route('**/api/integrations', route => {
      if (new URL(route.request().url()).pathname !== '/api/integrations')
        return route.fallback();
      return route.fulfill(
        json({
          data: [
            {
              id: 'snipeit',
              type: 'integration',
              attributes: {
                name: 'Snipe-IT',
                status: 'connected',
                capabilities: [],
                sync_summary: { sync_count: 0, error_count: 0 },
                needs_reauth: false,
                needs_reconsent: false,
              },
            },
          ],
        })
      );
    });
    await authenticatedPage.route('**/api/integrations/health', route =>
      route.fulfill(
        json({
          data: {
            type: 'integration-health',
            attributes: { overall: 'healthy' },
          },
        })
      )
    );

    let deleteCalled = false;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/connect',
      async route => {
        if (route.request().method() === 'DELETE') {
          deleteCalled = true;
          // Mock the disconnected state
          await authenticatedPage.route('**/api/integrations', r => {
            if (new URL(r.request().url()).pathname !== '/api/integrations')
              return r.fallback();
            return r.fulfill(
              json({
                data: [
                  {
                    id: 'snipeit',
                    type: 'integration',
                    attributes: {
                      name: 'Snipe-IT',
                      status: 'disconnected',
                      capabilities: [],
                      sync_summary: { sync_count: 0, error_count: 0 },
                      needs_reauth: false,
                      needs_reconsent: false,
                    },
                  },
                ],
              })
            );
          });
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
    await expect(snipeitPanel).toContainText('Connected');

    // Open settings modal where disconnect button lives
    await snipeitPanel.getByRole('button', { name: /settings/i }).click();

    const disconnectButton = authenticatedPage.locator(
      '[data-testid="snipeit-disconnect-button"]'
    );
    await expect(disconnectButton).toBeVisible();

    // Initiate disconnect
    await disconnectButton.click();

    // Verify delete was called and UI updates
    await expect(async () => {
      expect(deleteCalled).toBe(true);
      await expect(snipeitPanel).toContainText('Disconnected');
    }).toPass({ timeout: 5000 });
  });
});

test.describe('Snipe-IT Webhook URL', () => {
  const webhookUrl = (token: string) => ({
    data: {
      id: 'snipeit-webhook-url',
      type: 'webhook-url',
      attributes: {
        webhook_url: `https://pms.example.com/api/integrations/snipeit/webhook/${token}`,
        message:
          'Configure this URL in your Snipe-IT instance under Admin > Settings > Webhooks.',
      },
    },
  });

  test('regenerating the webhook URL shows the new URL once confirmed', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);
    await authenticatedPage.route('**/api/integrations', route => {
      if (new URL(route.request().url()).pathname !== '/api/integrations')
        return route.fallback();
      return route.fulfill(
        json({
          data: [
            {
              id: 'snipeit',
              type: 'integration',
              attributes: {
                name: 'Snipe-IT',
                status: 'connected',
                capabilities: [],
                sync_summary: { sync_count: 0, error_count: 0 },
                needs_reauth: false,
                needs_reconsent: false,
              },
            },
          ],
        })
      );
    });

    let rotateRequests = 0;
    await authenticatedPage.route(
      '**/api/integrations/snipeit/webhook-url',
      route => route.fulfill(json(webhookUrl('old-token')))
    );
    await authenticatedPage.route(
      '**/api/integrations/snipeit/webhook-url/rotate',
      route => {
        if (route.request().method() !== 'POST') return route.fallback();
        rotateRequests += 1;
        return route.fulfill(json(webhookUrl('new-token')));
      }
    );

    await authenticatedPage.goto('/integrations');

    const snipeitPanel = authenticatedPage.getByTestId(
      'integration-panel-snipeit'
    );
    await snipeitPanel.getByTestId('get-webhook-url-snipeit').click();

    const urlDialog = authenticatedPage.getByRole('dialog', {
      name: 'Snipe-IT Webhook URL',
    });
    await expect(urlDialog).toContainText('/webhook/old-token');

    await urlDialog.getByTestId('regenerate-webhook-url').click();
    const confirmation = authenticatedPage.getByRole('alertdialog', {
      name: 'Regenerate the webhook URL?',
    });
    await confirmation.getByRole('button', { name: 'Regenerate URL' }).click();

    await expect(confirmation).toBeHidden();
    await expect(urlDialog).toContainText('/webhook/new-token');
    await expect(urlDialog).not.toContainText('/webhook/old-token');
    expect(rotateRequests).toBe(1);
  });
});

/**
 * Helper: mock snipeit settings endpoint to return 404 (no settings configured).
 */
async function page_mockSnipeItSettingsNotFound(
  page: import('@playwright/test').Page
) {
  await page.route('**/api/integrations/snipeit/settings', route => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: [{ detail: 'No Snipe-IT settings found for this user' }],
        }),
      });
    }
    return route.fallback();
  });
}
