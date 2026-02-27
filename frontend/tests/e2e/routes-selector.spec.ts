import { test, expect } from './fixtures';

test.describe('RouteSelector Component', () => {
  test.beforeEach(async ({ authenticatedPage: page }) => {
    // Navigate to the test sandbox for the RouteSelector
    await page.goto('/test-sandbox/route-selector');
  });

  test('should display placeholder initially', async ({ page }) => {
    const combobox = page.getByRole('combobox', { name: 'Select Route' });
    await expect(combobox).toHaveText('Select a route...');
  });

  test('should allow searching and selecting a route', async ({ page }) => {
    // Mock the API response for routes
    await page.route('**/api/routes?*', async route => {
      const url = new URL(route.request().url());
      const query = url.searchParams.get('name') || '';

      const allRoutes = [
        {
          id: '1',
          type: 'routes',
          attributes: { name: 'Local Park Loop', description: '5km loop' },
        },
        {
          id: '2',
          type: 'routes',
          attributes: { name: 'Mountain Ridge Trail' },
        },
        { id: '3', type: 'routes', attributes: { name: 'City Center Run' } },
      ];

      const filtered = query
        ? allRoutes.filter(r =>
            r.attributes.name.toLowerCase().includes(query.toLowerCase())
          )
        : allRoutes;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: filtered }),
      });
    });

    const combobox = page.getByRole('combobox', { name: 'Select Route' });
    await combobox.click();

    // Verify list is populated
    await expect(page.getByText('Local Park Loop')).toBeVisible();
    await expect(page.getByText('Mountain Ridge Trail')).toBeVisible();

    // Search for a specific route
    const searchInput = page.getByPlaceholder('Search routes...');
    await searchInput.fill('Mountain');

    // Wait for debounce and search
    await expect(page.getByText('Mountain Ridge Trail')).toBeVisible();
    await expect(page.getByText('Local Park Loop')).not.toBeVisible();

    // Select the route
    await page.getByText('Mountain Ridge Trail').click();

    // Verify it was selected and popover closed
    await expect(combobox).toHaveText('Mountain Ridge Trail');

    // Verify the state output in the sandbox
    const stateOutput = page.getByTestId('selected-value');
    await expect(stateOutput).toContainText('"selectedRouteId": "2"');
  });

  test('should allow clearing the selection', async ({ page }) => {
    // Mock the API response
    await page.route('**/api/routes?*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [
            { id: '1', type: 'routes', attributes: { name: 'Test Route' } },
          ],
        }),
      });
    });

    // Select the route
    const combobox = page.getByRole('combobox', { name: 'Select Route' });
    await combobox.click();
    await page.getByText('Test Route').click();

    await expect(combobox).toHaveText('Test Route');

    // Deselect by clicking "Clear Selection" button in the sandbox
    await page.getByTestId('clear-btn').click();

    // Verify it's cleared
    await expect(combobox).toHaveText('Select a route...');
    const stateOutput = page.getByTestId('selected-value');
    await expect(stateOutput).toContainText('"selectedRouteId": null');
  });

  test('should show empty state for no results', async ({ page }) => {
    // Mock empty API response
    await page.route('**/api/routes?*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: [] }),
      });
    });

    const combobox = page.getByRole('combobox', { name: 'Select Route' });
    await combobox.click();

    const searchInput = page.getByPlaceholder('Search routes...');
    await searchInput.fill('Nonexistent Route');

    await expect(page.getByText('No routes found.')).toBeVisible();
    await expect(page.getByText('Create new route...')).toBeVisible();
  });
});
