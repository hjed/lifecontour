import { test, expect } from './fixtures';
import { APIRequestContext } from '@playwright/test';
import { FRONTEND_TEST_URL } from './utils/frontend-test-config';

// Helper to create a journal via API
async function createJournalViaApi(
  request: APIRequestContext,
  title: string,
  start: string = new Date().toISOString()
): Promise<string> {
  const response = await request.post(`${FRONTEND_TEST_URL}/api/journals`, {
    data: {
      data: {
        type: 'journals',
        attributes: {
          title,
          content: '',
          event_date_range: { start, end: start },
        },
      },
    },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return body.data.id;
}

// Helper to create a series via API
async function createSeriesViaApi(
  request: APIRequestContext,
  name: string
): Promise<string> {
  const response = await request.post(
    `${FRONTEND_TEST_URL}/api/journals/series`,
    {
      data: {
        data: {
          type: 'journal-series',
          attributes: { name },
        },
      },
    }
  );
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return body.data.id;
}

// Helper to add a journal to a series via API
async function addToSeriesViaApi(
  request: APIRequestContext,
  journalId: string,
  seriesId: string
): Promise<void> {
  const response = await request.post(
    `${FRONTEND_TEST_URL}/api/journals/${journalId}/relationships/series`,
    {
      data: { data: { type: 'journal-series', id: seriesId } },
    }
  );
  expect(response.ok()).toBeTruthy();
}

test.describe('Journal Series', () => {
  test.afterEach(async ({ request }) => {
    try {
      // Delete E2E series (member journals are left; deleted below)
      const seriesResponse = await request.get(
        `${FRONTEND_TEST_URL}/api/journals/series`
      );
      if (seriesResponse.ok()) {
        const body = await seriesResponse.json();
        for (const series of body.data) {
          if (series.attributes.name.startsWith('E2E Series')) {
            await request.delete(
              `${FRONTEND_TEST_URL}/api/journals/series/${series.id}`
            );
          }
        }
      }
      // Delete E2E journals
      const searchResponse = await request.get(
        `${FRONTEND_TEST_URL}/api/journals?search=E2E Series`
      );
      if (searchResponse.ok()) {
        const body = await searchResponse.json();
        for (const journal of body.data) {
          await request.delete(
            `${FRONTEND_TEST_URL}/api/journals/${journal.id}`
          );
        }
      }
    } catch (e) {
      console.debug('Cleanup failed:', e);
    }
  });

  test('creates a series from the journal detail view', async ({
    authenticatedPage,
    request,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now();
    const journalTitle = `E2E Series Member - ${suffix}`;
    const seriesName = `E2E Series Created - ${suffix}`;
    const journalId = await createJournalViaApi(request, journalTitle);

    await page.goto(`/journals/${journalId}`);
    await expect(
      page.getByRole('heading', { name: journalTitle, exact: true }).first()
    ).toBeVisible();

    // Open the series popover and create a new series inline
    await page.getByTestId('add-series-button').click();
    const nameInput = page.getByTestId('new-series-name-input');
    await expect(nameInput).toBeVisible();
    await nameInput.fill(seriesName);

    const addResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/relationships/series') &&
        response.request().method() === 'POST' &&
        response.status() === 204
    );
    await page.getByRole('button', { name: 'Create & Add' }).click();
    await addResponsePromise;

    // The badge for the new series appears on the detail page
    await expect(
      page.getByTestId('series-badges').getByText(seriesName)
    ).toBeVisible();
  });

  test('series badge navigates to the series page listing members', async ({
    authenticatedPage,
    request,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now();
    const journalTitle = `E2E Series Nav Member - ${suffix}`;
    const seriesName = `E2E Series Nav - ${suffix}`;
    const journalId = await createJournalViaApi(request, journalTitle);
    const seriesId = await createSeriesViaApi(request, seriesName);
    await addToSeriesViaApi(request, journalId, seriesId);

    await page.goto(`/journals/${journalId}`);
    const badgeLink = page
      .getByTestId(`series-badge-${seriesId}`)
      .getByRole('link', { name: new RegExp(seriesName) });
    await expect(badgeLink).toBeVisible();
    await badgeLink.click();

    await page.waitForURL(`**/journals/series/${seriesId}`);
    await expect(page.getByTestId('series-name')).toHaveText(seriesName);
    await expect(page.getByTestId(`series-member-${journalId}`)).toBeVisible();
    await expect(
      page.getByTestId('series-members').getByText(journalTitle)
    ).toBeVisible();
  });

  test('removes a journal from a series on the series page', async ({
    authenticatedPage,
    request,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now();
    const journalTitle = `E2E Series Remove Member - ${suffix}`;
    const seriesName = `E2E Series Remove - ${suffix}`;
    const journalId = await createJournalViaApi(request, journalTitle);
    const seriesId = await createSeriesViaApi(request, seriesName);
    await addToSeriesViaApi(request, journalId, seriesId);

    await page.goto(`/journals/series/${seriesId}`);
    await expect(page.getByTestId(`series-member-${journalId}`)).toBeVisible();

    const removeResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/relationships/series/') &&
        response.request().method() === 'DELETE' &&
        response.status() === 204
    );
    await page.getByTestId(`remove-member-${journalId}`).click();
    await removeResponsePromise;

    await expect(page.getByTestId(`series-member-${journalId}`)).toBeHidden();
    await expect(
      page.getByText('No journals in this series yet.')
    ).toBeVisible();
  });

  test('merges another series into this one, merging same-day journals', async ({
    authenticatedPage,
    request,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now();
    // A fixed past instant: the e2e user has no timezone, so the backend
    // pairs by the UTC day, and 09:00Z is the same day in UTC.
    const sameDay = '2025-03-03T09:00:00.000Z';
    const sourceName = `E2E Series Merge Source - ${suffix}`;
    const destinationName = `E2E Series Merge Destination - ${suffix}`;
    const sourceTitle = `E2E Series Merge Old - ${suffix}`;
    const sourceJournalId = await createJournalViaApi(
      request,
      sourceTitle,
      sameDay
    );
    const destinationJournalId = await createJournalViaApi(
      request,
      `E2E Series Merge New - ${suffix}`,
      sameDay
    );
    const sourceId = await createSeriesViaApi(request, sourceName);
    const destinationId = await createSeriesViaApi(request, destinationName);
    await addToSeriesViaApi(request, sourceJournalId, sourceId);
    await addToSeriesViaApi(request, destinationJournalId, destinationId);

    await page.goto(`/journals/series/${destinationId}`);
    await expect(page.getByTestId('series-name')).toHaveText(destinationName);
    await page.getByTestId('merge-series-button').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByTestId('merge-series-source').click();
    await page.getByRole('option', { name: sourceName }).click();
    await dialog
      .getByRole('radiogroup', { name: 'Title' })
      .getByRole('radio', { name: 'Use merged-in series' })
      .click();

    const day = dialog.getByTestId('series-merge-day-2025-03-03');
    await expect(day).toContainText('Will merge; title differs');
    await expect(
      day.getByRole('checkbox', { name: 'Merge 3 Mar 2025' })
    ).toBeChecked();

    const mergeResponsePromise = page.waitForResponse(
      response =>
        response
          .url()
          .endsWith(`/api/journals/series/${destinationId}/merge`) &&
        response.request().method() === 'POST'
    );
    await dialog.getByTestId('confirm-merge-series').click();
    expect((await mergeResponsePromise).status()).toBe(200);

    await expect(dialog).toBeHidden();
    const member = page.getByTestId(`series-member-${destinationJournalId}`);
    await expect(member).toContainText(sourceTitle);
    await expect(
      page.getByTestId(`series-member-${sourceJournalId}`)
    ).toHaveCount(0);

    await page.goto(`/journals/series/${sourceId}`);
    await expect(page.getByText(/Failed to load series/)).toBeVisible();
  });
});
