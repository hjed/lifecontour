import { test, expect } from './fixtures';

test.describe('Gear Usage Editor', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    // Standard mock for gear items
    await authenticatedPage.route('**/api/gear-items*', async route => {
      await route.fulfill({
        status: 200,
        json: {
          data: [
            {
              id: 'g1',
              type: 'gear-items',
              attributes: { name: 'Test Climbing Rope' },
            },
          ],
        },
      });
    });
  });

  test('conditionally shows buffer dates when Snipe-IT is connected', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    // Mock integrations endpoint to show Snipe-IT as connected
    await page.route('**/api/integrations', async route => {
      await route.fulfill({
        status: 200,
        json: {
          data: [
            {
              id: 'snipeit',
              type: 'integration',
              attributes: {
                name: 'Snipe-IT',
                status: 'connected',
                capabilities: ['gear_sync'],
                needs_reauth: false,
                needs_reconsent: false,
                sync_summary: {
                  sync_count: 0,
                  error_count: 0,
                  last_sync_time: null,
                },
              },
            },
          ],
        },
      });
    });

    await page.goto('/journals/new');

    // Select Gear Usage type
    await page.getByLabel(/^gear usage$/i).check();

    // Verify gear item selector is visible
    await expect(page.getByTestId('gear-usage-type-editor')).toBeVisible();
    await expect(page.getByTestId('gear-item-selector')).toBeVisible();

    // Verify buffer dates are visible because Snipe-IT is connected
    await expect(page.getByTestId('checkout-date-input')).toBeVisible();
    await expect(page.getByTestId('checkin-date-input')).toBeVisible();
  });

  test('hides buffer dates when Snipe-IT is disconnected', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    // Mock integrations endpoint to show Snipe-IT as disconnected
    await page.route('**/api/integrations', async route => {
      await route.fulfill({
        status: 200,
        json: {
          data: [
            {
              id: 'snipeit',
              type: 'integration',
              attributes: {
                name: 'Snipe-IT',
                status: 'disconnected',
                capabilities: ['gear_sync'],
                needs_reauth: false,
                needs_reconsent: false,
                sync_summary: {
                  sync_count: 0,
                  error_count: 0,
                  last_sync_time: null,
                },
              },
            },
          ],
        },
      });
    });

    await page.goto('/journals/new');

    // Select Gear Usage type
    await page.getByLabel(/^gear usage$/i).check();

    // Verify gear item selector is visible
    await expect(page.getByTestId('gear-usage-type-editor')).toBeVisible();
    await expect(page.getByTestId('gear-item-selector')).toBeVisible();

    // Verify buffer dates are NOT visible because Snipe-IT is disconnected
    await expect(page.getByTestId('checkout-date-input')).toBeHidden();
    await expect(page.getByTestId('checkin-date-input')).toBeHidden();
  });
});
