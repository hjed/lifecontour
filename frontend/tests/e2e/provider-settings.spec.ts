/**
 * Parametrized e2e tests for provider settings panels.
 *
 * The Immich and Snipe-IT settings panels share the same structural flow:
 * the panel renders in the integration list and a Settings button opens a modal
 * containing the provider's configuration form. These shared behaviors are
 * covered here once, parametrized over each provider.
 *
 * Provider-specific request contracts (connect/save/disconnect) live in
 * immich-settings.spec.ts and snipeit-settings.spec.ts. Pure form rendering and
 * client-side validation are unit-tested in ImmichSettings.test.tsx /
 * SnipeItSettings.test.tsx.
 */

import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

interface ProviderConfig {
  id: string;
  name: string;
  capabilities: string[];
  formTestId: string;
  inputTestIds: string[];
  saveButtonTestId: string;
  /** Provider-specific route stubs required for the settings modal to render. */
  setupModalRoutes?: (page: Page) => Promise<void>;
}

const PROVIDERS: ProviderConfig[] = [
  {
    id: 'immich',
    name: 'Immich',
    capabilities: ['contacts_sync', 'album_sync'],
    formTestId: 'immich-settings-form',
    inputTestIds: ['immich-server-url-input', 'immich-api-key-input'],
    saveButtonTestId: 'immich-connect-button',
  },
  {
    id: 'snipeit',
    name: 'Snipe-IT',
    capabilities: ['gear_sync', 'maintenance_sync', 'checkout_sync'],
    formTestId: 'snipeit-settings-form',
    inputTestIds: ['snipeit-base-url-input', 'snipeit-user-id-input'],
    saveButtonTestId: 'snipeit-settings-save-button',
    // Snipe-IT loads its saved settings when the modal opens; stub "none yet".
    setupModalRoutes: async (page: Page) => {
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
    },
  },
];

async function setupBaseRoutes(page: Page, provider: ProviderConfig) {
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

  await page.route('**/api/integrations', route => {
    if (new URL(route.request().url()).pathname !== '/api/integrations') {
      return route.fallback();
    }
    return route.fulfill(
      json({
        data: [
          {
            id: provider.id,
            type: 'integration',
            attributes: {
              name: provider.name,
              status: 'disconnected',
              capabilities: provider.capabilities,
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

  await page.route('**/api/integrations/*/sync-history**', route =>
    route.fulfill(json({ data: [], meta: { total: 0, page: 1, pageSize: 5 } }))
  );
}

test.describe('Provider Settings Panels', () => {
  for (const provider of PROVIDERS) {
    test.describe(provider.name, () => {
      test('panel is visible in the integration list', async ({
        authenticatedPage,
      }) => {
        await setupBaseRoutes(authenticatedPage, provider);

        await authenticatedPage.goto('/integrations');

        const panel = authenticatedPage.locator(
          `[data-testid="integration-panel-${provider.id}"]`
        );
        await expect(panel).toBeVisible();
        await expect(panel).toContainText(provider.name);
        await expect(panel).toContainText('Disconnected');
      });

      test('settings modal opens and shows the configuration form', async ({
        authenticatedPage,
      }) => {
        await setupBaseRoutes(authenticatedPage, provider);
        await provider.setupModalRoutes?.(authenticatedPage);

        await authenticatedPage.goto('/integrations');

        const panel = authenticatedPage.locator(
          `[data-testid="integration-panel-${provider.id}"]`
        );
        await expect(panel).toBeVisible();

        await panel.getByRole('button', { name: /settings/i }).click();

        const form = authenticatedPage.locator(
          `[data-testid="${provider.formTestId}"]`
        );
        await expect(form).toBeVisible();

        for (const inputTestId of provider.inputTestIds) {
          await expect(
            authenticatedPage.locator(`[data-testid="${inputTestId}"]`)
          ).toBeVisible();
        }
        await expect(
          authenticatedPage.locator(
            `[data-testid="${provider.saveButtonTestId}"]`
          )
        ).toBeVisible();
      });
    });
  }
});
