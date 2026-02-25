/**
 * E2E Tests for Journal Creation UI Flow
 *
 * Tests the creation of journals through the UI with different types and inline editors.
 */

import { test, expect } from './fixtures';

test.describe('Journal Creation UI Flow', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    authenticatedPage.on('console', msg => {
      console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`);
    });
    // Log API responses for journals to see backend validation errors
    authenticatedPage.on('response', async response => {
      if (
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST'
      ) {
        console.log(`[API Response] ${response.status()}`);
        if (!response.ok()) {
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

    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    const title = `Mood Check ${Date.now()}`;
    await page.getByLabel(/title/i).fill(title);
    await page.getByLabel(/content/i).fill('Feeling neutral today.');

    // Select MOOD_RATING type
    await page.getByLabel(/^mood rating$/i).check();

    // Verify editors appear and default to 5
    await expect(page.getByTestId('mood-rating-type-editor')).toBeVisible();
    await expect(page.getByTestId('mood-value-display')).toHaveText('5');

    // Submit form
    const createButton = page.getByRole('button', { name: /create journal/i });
    await createButton.click();

    // Verify redirection to details page
    await page.waitForURL(/\/journals\/\d+/);

    // Verify type badge and mood data exist in the UI
    await expect(page.getByTestId('type-badge-mood_rating')).toBeVisible();
  });

  test('should create a PLAN journal', async ({ authenticatedPage }) => {
    const page = authenticatedPage;

    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    const title = `Trip Plan ${Date.now()}`;
    await page.getByLabel(/title/i).fill(title);
    await page.getByLabel(/content/i).fill('Plan for upcoming trip.');

    // Select PLAN type
    await page.getByLabel(/^plan$/i).check();

    // Verify plan editor
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

    const createButton = page.getByRole('button', { name: /create journal/i });
    await createButton.click();

    await page.waitForURL(/\/journals\/\d+/);
    await expect(page.getByTestId('type-badge-plan')).toBeVisible();
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
    const calendarJson = await calendarRes.json();
    const calendarId = calendarJson.data.id;

    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    await page.getByLabel(/title/i).fill(`Event ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Event details.');

    // Select EVENT type
    await page.getByLabel(/^event$/i).check();

    await expect(page.getByTestId('event-type-editor')).toBeVisible();
    await page
      .getByRole('checkbox', { name: /all-day event/i })
      .waitFor({ state: 'visible' });
    await page.getByTestId('calendar-id-input').fill(calendarId);

    // Check all-day to avoid Start/End time validation unless we want to fill them
    await page.getByRole('checkbox', { name: /all-day event/i }).check();

    const createButton = page.getByRole('button', { name: /create journal/i });
    await createButton.click();

    await page.waitForURL(/\/journals\/\d+/);
    await expect(page.getByTestId('type-badge-event')).toBeVisible();
  });

  test('should create a TRAVEL journal with locations', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    await page.getByLabel(/title/i).fill(`Trip ${Date.now()}`);
    await page
      .getByLabel(/content/i)
      .fill('Trip details regarding flights and accommodation.');

    // Select TRAVEL type
    await page.getByLabel(/^travel$/i).check();

    await expect(page.getByTestId('travel-type-editor')).toBeVisible();

    // Travel editor does not have inputs yet, so we just verify it renders properly
    await expect(page.getByText('Flights', { exact: true })).toBeVisible();

    const createButton = page.getByRole('button', { name: /create journal/i });
    await createButton.click();

    await page.waitForURL(/\/journals\/\d+/);
    await expect(page.getByTestId('type-badge-travel')).toBeVisible();
  });

  test('should create a PHOTO_ALBUM journal with immich ID', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    await page.getByLabel(/title/i).fill(`Photos ${Date.now()}`);
    await page
      .getByLabel(/content/i)
      .fill('A collection of photos from the recent trip.');

    // Select PHOTO_ALBUM type
    await page.getByLabel(/^photo album$/i).check();

    await expect(page.getByTestId('photo-album-type-editor')).toBeVisible();
    await page
      .getByTestId('immich-album-id-input')
      .waitFor({ state: 'visible' });
    await page
      .getByTestId('immich-album-id-input')
      .fill('223e4567-e89b-12d3-a456-426614174001');

    const createButton = page.getByRole('button', { name: /create journal/i });
    await createButton.click();

    await page.waitForURL(/\/journals\/\d+/);
    await expect(page.getByTestId('type-badge-photo_album')).toBeVisible();
  });
});
