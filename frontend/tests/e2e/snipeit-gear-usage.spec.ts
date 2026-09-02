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

    // Mock journal creation
    await page.route('**/api/journals', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          json: {
            data: {
              id: 'j1',
              type: 'journal',
              attributes: {
                title: 'Test Gear Usage',
                journal_type: 'GEAR_USAGE',
              },
            },
          },
        });
      } else {
        await route.continue();
      }
    });

    // Fill common journal fields
    await page.getByLabel(/title/i).fill('Testing Gear Usage');
    await page.getByLabel(/content/i).fill('Used the climbing rope today.');

    // Select a gear item
    await page.getByTestId('gear-item-selector').click();
    await page.getByText('Test Climbing Rope').click();
    await expect(page.getByTestId('gear-item-selector')).toContainText(
      'Test Climbing Rope'
    );

    // Fill buffer dates
    await page.getByTestId('checkout-date-input').fill('2026-05-21T10:00');
    await page.getByTestId('checkin-date-input').fill('2026-05-21T18:00');

    // Verify buffer dates are visible because Snipe-IT is connected
    await expect(page.getByTestId('checkout-date-input')).toBeVisible();
    await expect(page.getByTestId('checkin-date-input')).toBeVisible();

    // Submit
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/api/journals') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /create journal/i }).click(),
    ]);
    const requestPayload = request.postDataJSON();

    // Assert payload
    expect(requestPayload?.data?.attributes).toBeDefined();
    const attrs = requestPayload.data.attributes;
    expect(attrs.types).toContain('gear_usage');
    expect(attrs.type_data['gear_usage'].gear_item_id).toBe('g1');
    expect(attrs.type_data['gear_usage'].checkout_date).toContain(
      '2026-05-21T10:00'
    );
    expect(attrs.type_data['gear_usage'].checkin_date).toContain(
      '2026-05-21T18:00'
    );
  });

  // Note: the disconnected case — buffer date inputs withheld while the gear
  // selector stays — is unit-tested in GearUsageTypeEditor.test.tsx. The
  // connected test above keeps the create-form wiring and payload shape
  // covered end-to-end.
});
