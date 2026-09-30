import { test, expect } from './fixtures';
import { APIRequestContext, Page } from '@playwright/test';
import { FRONTEND_TEST_URL } from './utils/frontend-test-config';

// Helper to create a journal via API
async function createJournalViaApi(
  request: APIRequestContext,
  title: string,
  start: string = new Date().toISOString(),
  parentId?: string
): Promise<string> {
  const response = await request.post(`${FRONTEND_TEST_URL}/api/journals`, {
    data: {
      data: {
        type: 'journals',
        attributes: {
          title,
          content: '',
          event_date_range: { start, end: start },
          ...(parentId ? { parent_id: parentId } : {}),
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

interface SameDayMergeSeed {
  sourceId: string;
  destinationId: string;
  sourceName: string;
  sourceJournalId: string;
  destinationJournalId: string;
  sourceTitle: string;
}

/**
 * Two series with one journal each on the same UTC day (the e2e user has no
 * timezone, so the backend pairs by UTC day). With `destinationIsChild` the
 * destination journal is the source journal's child, and a journal cannot
 * absorb its own ancestor, so the pair's merge is refused.
 */
async function seedSameDayMerge(
  request: APIRequestContext,
  label: string,
  sameDay: string,
  destinationIsChild = false
): Promise<SameDayMergeSeed> {
  const suffix = Date.now();
  const sourceName = `E2E Series ${label} Source - ${suffix}`;
  const sourceTitle = `E2E Series ${label} Old - ${suffix}`;
  const sourceJournalId = await createJournalViaApi(
    request,
    sourceTitle,
    sameDay
  );
  const destinationJournalId = await createJournalViaApi(
    request,
    `E2E Series ${label} New - ${suffix}`,
    sameDay,
    destinationIsChild ? sourceJournalId : undefined
  );
  const sourceId = await createSeriesViaApi(request, sourceName);
  const destinationId = await createSeriesViaApi(
    request,
    `E2E Series ${label} Destination - ${suffix}`
  );
  await addToSeriesViaApi(request, sourceJournalId, sourceId);
  await addToSeriesViaApi(request, destinationJournalId, destinationId);
  return {
    sourceId,
    destinationId,
    sourceName,
    sourceJournalId,
    destinationJournalId,
    sourceTitle,
  };
}

/** Open the merge dialog on the destination's page with the source chosen. */
async function openMergeDialog(page: Page, seed: SameDayMergeSeed) {
  await page.goto(`/journals/series/${seed.destinationId}`);
  await page.getByTestId('merge-series-button').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByTestId('merge-series-source').click();
  await page.getByRole('option', { name: seed.sourceName }).click();
  return dialog;
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
    const seed = await seedSameDayMerge(
      request,
      'Merge',
      '2025-03-03T09:00:00.000Z'
    );

    const dialog = await openMergeDialog(page, seed);
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
          .endsWith(`/api/journals/series/${seed.destinationId}/merge`) &&
        response.request().method() === 'POST'
    );
    await dialog.getByTestId('confirm-merge-series').click();
    expect((await mergeResponsePromise).status()).toBe(200);

    await expect(dialog).toBeHidden();
    await expect(
      page.getByTestId(`series-member-${seed.destinationJournalId}`)
    ).toContainText(seed.sourceTitle);
    await expect(
      page.getByTestId(`series-member-${seed.sourceJournalId}`)
    ).toHaveCount(0);

    await page.goto(`/journals/series/${seed.sourceId}`);
    await expect(page.getByText(/Failed to load series/)).toBeVisible();
  });

  test('shows which same-day journals could not be merged', async ({
    authenticatedPage,
    request,
  }) => {
    const page = authenticatedPage;
    const seed = await seedSameDayMerge(
      request,
      'Merge Fail',
      '2025-03-10T09:00:00.000Z',
      true
    );

    const dialog = await openMergeDialog(page, seed);
    const day = dialog.getByTestId('series-merge-day-2025-03-10');
    await expect(day).toContainText('Will merge');

    await dialog.getByTestId('confirm-merge-series').click();

    await expect(day).toContainText('could not be merged');
    await expect(dialog.getByRole('status')).toContainText(
      'some same-day journals could not be merged'
    );
    await dialog.getByTestId('close-merge-series-result').click();
    await expect(dialog).toBeHidden();
    for (const journalId of [seed.sourceJournalId, seed.destinationJournalId]) {
      await expect(
        page.getByTestId(`series-member-${journalId}`)
      ).toBeVisible();
    }
  });
});
