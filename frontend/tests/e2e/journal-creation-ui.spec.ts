/**
 * E2E Tests for Journal Creation UI Flow
 *
 * Tests the creation of journals through the UI with different types and inline editors.
 */

import { test, expect } from './fixtures';
import { type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared helpers — extracted to eliminate per-test duplication flagged by
// SonarQube. Each helper encapsulates a repeated sequence of actions.
// ---------------------------------------------------------------------------

/** Navigate to /journals/new and wait for the page to be fully loaded. */
async function navigateToNewJournal(page: Page) {
  await page.goto('/journals/new');
  await page.waitForLoadState('networkidle');
}

/**
 * Fill common fields, select the given journal type, and submit the creation form.
 * Returns after the form has been submitted (does NOT wait for redirect).
 */
async function fillAndSubmitJournal(
  page: Page,
  opts: { title: string; content: string; typeLabelRegex: RegExp }
) {
  await page.getByLabel(/title/i).fill(opts.title);
  await page.getByLabel(/content/i).fill(opts.content);
  await page.getByLabel(opts.typeLabelRegex).check();
  await page.getByRole('button', { name: /create journal/i }).click();
}

/**
 * Wait for redirect to a journal detail page and assert the given type badge is visible.
 * Returns the final URL so callers can extract the journal ID if needed.
 */
async function awaitCreationAndAssertBadge(
  page: Page,
  badgeTestId: string
): Promise<string> {
  await page.waitForURL(/\/journals\/\d+/);
  await expect(page.getByTestId(badgeTestId)).toBeVisible();
  return page.url();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Journal Creation UI Flow', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    const debugE2E = !!process.env.DEBUG_E2E;

    authenticatedPage.on('pageerror', exception => {
      console.log(
        `[Browser pageerror] ${exception.message} \n ${exception.stack}`
      );
    });

    authenticatedPage.on('console', msg => {
      const type = msg.type();
      // In normal runs, only log browser console errors/warnings to keep CI output manageable.
      // Set DEBUG_E2E=1 to log all console messages for deeper debugging.
      if (!debugE2E && type !== 'error' && type !== 'warning') {
        return;
      }
      console.log(`[Browser Console] ${type}: ${msg.text()}`);
    });
    // Log API errors for journals to surface backend validation failures
    authenticatedPage.on('response', async response => {
      if (
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST'
      ) {
        if (!response.ok()) {
          console.log(`[API Response] ${response.status()}`);
          try {
            const data = await response.json();
            console.log('[API JSON Body Error]', JSON.stringify(data, null, 2));
          } catch (e) {
            console.log('[API Body Parsing Error]', e);
          }
        }
      }
    });
  });

  test('should create a MOOD_RATING journal with default slider values', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    const title = `Mood Check ${Date.now()}`;
    await page.getByLabel(/title/i).fill(title);
    await page.getByLabel(/content/i).fill('Feeling neutral today.');
    await page.getByLabel(/^mood rating$/i).check();

    // Assert the editor is visible and defaults to 5 BEFORE submitting,
    // so navigation cannot race with these assertions.
    await expect(page.getByTestId('mood-rating-type-editor')).toBeVisible();
    await expect(page.getByTestId('mood-value-display')).toHaveText('5');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-mood_rating');

    // The type section is collapsed by default on the detail page.
    // We must expand it to assert on the type editors/displays inside it.
    await page.getByTestId('type-section-trigger-mood_rating').click();

    // Verify the persisted mood value (default 5) is shown on the detail page
    await expect(page.getByTestId('mood-value-display')).toHaveText('5');
  });

  test('should create a PLAN journal', async ({ authenticatedPage }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Trip Plan ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Plan for upcoming trip.');
    await page.getByLabel(/^plan$/i).check();

    // Verify plan editor is visible before adding a document
    await expect(page.getByTestId('plan-type-editor')).toBeVisible();

    await page.getByTestId('add-document-button').waitFor({ state: 'visible' });
    await page.getByTestId('add-document-button').click();
    await page.getByTestId('document-url-0').waitFor({ state: 'visible' });
    await page.getByTestId('document-url-0').fill('https://example.com/plan');
    await page.getByTestId('document-title-0').fill('Itinerary');

    // Web-first assertion avoids a race condition between Playwright fill and React Hook Form validation
    await expect(page.getByTestId('document-url-0')).toHaveValue(
      'https://example.com/plan'
    );
    await expect(page.getByTestId('document-title-0')).toHaveValue('Itinerary');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-plan');

    // The type section is collapsed by default on the detail page.
    await page.getByTestId('type-section-trigger-plan').click();

    // Verify the document was persisted and rendered on the detail page
    await expect(page.getByTestId('document-url-0')).toHaveValue(
      'https://example.com/plan'
    );
    await expect(page.getByTestId('document-title-0')).toHaveValue('Itinerary');
  });

  test('should create an EVENT journal with calendar info', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // Create a physical calendar via API to satisfy the foreign key constraint
    const calendarRes = await page.request.post('/api/calendars', {
      data: {
        data: {
          type: 'calendars',
          attributes: {
            name: `E2E Cal ${Date.now()}`,
            description: 'Created by e2e test',
          },
        },
      },
    });
    expect(calendarRes.ok()).toBeTruthy();
    const calendarJson = await calendarRes.json();
    expect(calendarJson.data).toBeDefined();
    expect(calendarJson.data.id).toBeDefined();
    const calendarId = calendarJson.data.id;

    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Event ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Event details.');
    await page.getByLabel(/^event$/i).check();

    await expect(page.getByTestId('event-type-editor')).toBeVisible();
    await page
      .getByRole('checkbox', { name: /all-day event/i })
      .waitFor({ state: 'visible' });
    await page.getByTestId('calendar-id-input').fill(calendarId);

    // Check all-day to avoid Start/End time validation unless we want to fill them
    await page.getByRole('checkbox', { name: /all-day event/i }).check();

    await page.getByRole('button', { name: /create journal/i }).click();
    await awaitCreationAndAssertBadge(page, 'manage-type-event');
  });

  test('should create a TRAVEL journal with locations', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await fillAndSubmitJournal(page, {
      title: `Trip ${Date.now()}`,
      content: 'Trip details regarding flights and accommodation.',
      typeLabelRegex: /^travel$/i,
    });

    // fillAndSubmitJournal already clicked Create Journal; wait for the redirect
    // and verify the travel type badge appears on the detail page.
    await awaitCreationAndAssertBadge(page, 'manage-type-travel');
  });

  test('should create a PHOTO_ALBUM journal with immich ID', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Photos ${Date.now()}`);
    await page
      .getByLabel(/content/i)
      .fill('A collection of photos from the recent trip.');
    await page.getByLabel(/^photo album$/i).check();

    await expect(page.getByTestId('photo-album-type-editor')).toBeVisible();
    await page
      .getByTestId('immich-album-id-input')
      .waitFor({ state: 'visible' });
    await page
      .getByTestId('immich-album-id-input')
      .fill('223e4567-e89b-12d3-a456-426614174001');

    await page.getByRole('button', { name: /create journal/i }).click();
    await awaitCreationAndAssertBadge(page, 'manage-type-photo_album');
  });

  test('should create a FITNESS journal and verify ActivityStats render', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Run ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Morning 5k run.');

    // Select the FITNESS type
    await page.getByLabel(/^fitness$/i).check();

    // Verify editor is visible
    await expect(page.getByTestId('fitness-type-editor')).toBeVisible();

    // Fill fitness stats
    await page.getByTestId('distance-input').fill('5000');
    await page.getByTestId('duration-input').fill('1500'); // 25 minutes
    await page.getByTestId('hr-avg-input').fill('155');

    // Upload a mock GPX file to trigger Map rendering
    const gpxContent = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093"><ele>10</ele><time>2026-01-01T00:00:00Z</time></trkpt>
      <trkpt lat="-33.8690" lon="151.2095"><ele>12</ele><time>2026-01-01T00:00:10Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>`;

    await page.getByTestId('gpx-file-input').setInputFiles({
      name: 'test-track.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from(gpxContent),
    });

    await page.getByRole('button', { name: /create journal/i }).click();

    // Verify redirect and badge
    await awaitCreationAndAssertBadge(page, 'manage-type-fitness');

    // Expand type section
    await page.getByTestId('type-section-trigger-fitness').click();

    // Verify stats are rendered in read-only mode by ActivityStats
    await expect(page.getByTestId('activity-stats-grid')).toBeVisible();
    await expect(page.getByTestId('stat-distance')).toHaveText('5.00 km');
    await expect(page.getByTestId('stat-duration')).toHaveText('25:00');
    await expect(page.getByTestId('stat-pace')).toHaveText('5:00 /km');
    await expect(page.getByTestId('stat-hr')).toHaveText('155 bpm');

    // Verify map is rendered
    await expect(page.getByTestId('gpx-track-display')).toBeVisible();
    await expect(page.locator('.leaflet-container')).toBeVisible();
  });
});
