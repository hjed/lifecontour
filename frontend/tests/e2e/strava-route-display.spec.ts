/**
 * E2E test for verifying GPX route display on journal detail pages.
 *
 * This test creates a journal with the FITNESS type and attaches a GPX
 * route via the API, then navigates to the journal detail page and
 * verifies the route name is visible in the routes editor section.
 *
 * Covers the product specification requirement:
 * "import activity with GPS track, verify route visible on journal detail page"
 */

import { expect, test } from './fixtures';
import { TestDataManager } from './data-management';

const SAMPLE_GPX_DATA = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="StravaGPXGenerator">
  <trk>
    <name>Morning Run</name>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093">
        <ele>50.0</ele>
        <time>2026-03-20T08:00:00Z</time>
      </trkpt>
      <trkpt lat="-33.8700" lon="151.2100">
        <ele>48.0</ele>
        <time>2026-03-20T08:05:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>`;

test.describe('Strava GPX Route Display', () => {
  test('journal with GPX route shows route name on detail page', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    await dataManager.clearAllJournals();

    // Create a journal with FITNESS type
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const journal = await dataManager.createJournal({
      title: 'Morning Run with GPS',
      content: 'Easy jog through the park with route tracking.',
      event_date_range: {
        start: yesterday.toISOString(),
        end: yesterday.toISOString(),
      },
      types: ['fitness'],
      type_data: {
        fitness: {
          distance: 10000,
          elevation_gain: 150,
          duration: 3400,
        },
      },
    });

    // Attach a route via API
    await dataManager.createRoute(journal.id, {
      name: 'Morning Run Route',
      gpx_data: SAMPLE_GPX_DATA,
    });

    // Register cleanup
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate to journal detail page
    await authenticatedPage.goto(`/journals/${journal.id}`);

    // Wait for the journal to load
    await expect(
      authenticatedPage.getByTestId('journal-title-field')
    ).toBeVisible();

    // Expand the Fitness type section (it's collapsed by default)
    const fitnessToggle = authenticatedPage.getByTestId(
      'type-section-trigger-fitness'
    );
    await expect(fitnessToggle).toBeVisible();
    await fitnessToggle.click();

    // Wait for the fitness editor to be visible (the section is now expanded)
    await expect(
      authenticatedPage.getByTestId('fitness-type-editor')
    ).toBeVisible();

    // Verify the routes editor section is visible with the route name.
    // The routes are fetched via API after the editor mounts, so we need
    // to wait for the route name to appear.
    const routesEditor = authenticatedPage.getByTestId('journal-routes-editor');
    await expect(routesEditor).toBeVisible({ timeout: 10000 });
    await expect(routesEditor).toContainText('Morning Run Route');
  });
});
