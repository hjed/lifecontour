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

test.describe('Snipe-IT Integration Settings', () => {
  test('snipeit panel is visible in integration list', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);

    await authenticatedPage.goto('/integrations');

    // Verify the Snipe-IT panel exists and shows disconnected status
    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();
    await expect(snipeitPanel).toContainText('Snipe-IT');
    await expect(snipeitPanel).toContainText('Disconnected');
  });

  test('settings modal opens and shows the Snipe-IT configuration form', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);

    // Mock 404 for settings (no settings configured yet)
    await page_mockSnipeItSettingsNotFound(authenticatedPage);

    await authenticatedPage.goto('/integrations');

    // Click the Settings button on the Snipe-IT panel
    const snipeitPanel = authenticatedPage.locator(
      '[data-testid="integration-panel-snipeit"]'
    );
    await expect(snipeitPanel).toBeVisible();

    const settingsButton = snipeitPanel.getByRole('button', {
      name: /settings/i,
    });
    await settingsButton.click();

    // Verify modal opens and has the correct form fields
    const form = authenticatedPage.locator(
      '[data-testid="snipeit-settings-form"]'
    );
    await expect(form).toBeVisible();

    await expect(
      authenticatedPage.locator('[data-testid="snipeit-base-url-input"]')
    ).toBeVisible();
    await expect(
      authenticatedPage.locator('[data-testid="snipeit-user-id-input"]')
    ).toBeVisible();
    await expect(
      authenticatedPage.locator('[data-testid="snipeit-settings-save-button"]')
    ).toBeVisible();
  });

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
              base_url: savedPayload?.base_url,
              snipeit_user_id: savedPayload?.snipeit_user_id ?? null,
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

  test('settings modal shows validation error for invalid URL', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);
    await page_mockSnipeItSettingsNotFound(authenticatedPage);

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

    // Enter invalid URL
    const baseUrlInput = authenticatedPage.locator(
      '[data-testid="snipeit-base-url-input"]'
    );
    await expect(baseUrlInput).toBeVisible();
    await baseUrlInput.fill('not-a-valid-url');

    // Try to submit
    const saveButton = authenticatedPage.locator(
      '[data-testid="snipeit-settings-save-button"]'
    );
    await saveButton.click();

    // Verify validation error appears
    await expect(
      authenticatedPage.getByText(/must be a valid url/i)
    ).toBeVisible();
  });

  test('settings modal populates existing settings on open', async ({
    authenticatedPage,
  }) => {
    await setupBaseRoutes(authenticatedPage);

    // Mock existing settings
    await authenticatedPage.route(
      '**/api/integrations/snipeit/settings',
      route =>
        route.fulfill(
          json({
            base_url: 'https://existing-snipeit.example.com',
            snipeit_user_id: '99',
          })
        )
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

    // Verify form is pre-populated with existing settings
    const baseUrlInput = authenticatedPage.locator(
      '[data-testid="snipeit-base-url-input"]'
    );
    await expect(baseUrlInput).toHaveValue(
      'https://existing-snipeit.example.com'
    );

    const userIdInput = authenticatedPage.locator(
      '[data-testid="snipeit-user-id-input"]'
    );
    await expect(userIdInput).toHaveValue('99');
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
