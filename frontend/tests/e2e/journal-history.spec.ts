/**
 * E2E Tests for Journal Activity History
 *
 * Tests the Activity Feed at the bottom of the journal detail page: it renders
 * field-level history with provenance and paginates, mirroring the contact
 * activity feed (`contact-activity-feed.spec.ts`).
 *
 * Journal history is produced by an ASYNCHRONOUS projection consumer
 * (domain event -> outbox relay -> consumer -> field_history). There is no
 * frontend request that signals when projection completes, so tests that depend
 * on a just-made change poll the history API with `expect.poll`/`toPass` until
 * the entry appears (per the async-data-loads guidance) rather than asserting
 * immediately. Empty/loading/error states are covered deterministically by the
 * RTL unit tests (a freshly-created journal always projects a `__created__`
 * entry, so an empty feed is not a deterministic E2E state).
 *
 * Each test creates its own data; no conditional/skip logic.
 */

import { test, expect } from './fixtures';

/** Poll the journal history API until an entry matching the predicate appears. */
async function waitForHistoryEntry(
  request: import('@playwright/test').APIRequestContext,
  journalId: string,
  matches: (attrs: {
    field_name: string;
    source: string;
    new_value: string | null;
  }) => boolean
): Promise<void> {
  await expect(async () => {
    const response = await request.get(`/api/journals/${journalId}/history`);
    expect(response.ok()).toBeTruthy();
    const json = await response.json();
    expect(Array.isArray(json.data)).toBe(true);
    const found = json.data.some(
      (entry: { attributes: Parameters<typeof matches>[0] }) =>
        matches(entry.attributes)
    );
    expect(found).toBe(true);
  }).toPass({ timeout: 30000 });
}

test.describe('Journal Activity History', () => {
  test('displays the Activity Feed section on the journal detail page', async ({
    journalsWithData,
  }) => {
    const { page, journals } = journalsWithData;
    const journal = journals[0];

    await page.goto(`/journals/${journal.id}`);
    await expect(page).toHaveURL(new RegExp(`/journals/${journal.id}`));

    const activityFeedHeading = page.getByRole('heading', {
      name: /Activity/i,
    });
    await expect(activityFeedHeading).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('activity-feed')).toBeVisible();
  });

  test('shows a journal edit at the bottom with UI provenance once projected', async ({
    journalsWithData,
  }) => {
    const { page, journals } = journalsWithData;
    const journal = journals[0];

    // Edit the journal title via the UI/API path (records `ui` provenance).
    const updateResponse = await page.request.patch(
      `/api/journals/${journal.id}`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: {
          data: {
            type: 'journals',
            id: journal.id,
            attributes: { title: 'Updated Journal Title' },
          },
        },
      }
    );
    expect(updateResponse.ok()).toBeTruthy();

    // History is projected asynchronously — wait for the title change to land.
    await waitForHistoryEntry(
      page.request,
      journal.id,
      attrs =>
        attrs.field_name === 'title' &&
        attrs.source === 'ui' &&
        attrs.new_value === 'Updated Journal Title'
    );

    // The feed (at the bottom of the detail screen) renders the change with the
    // UI provenance indicator.
    await page.goto(`/journals/${journal.id}`);
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    const feed = page.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(feed.getByTestId('provenance-trigger-ui').first()).toBeVisible(
      {
        timeout: 10000,
      }
    );
  });

  test('records history for multiple journal types (NOTE, EVENT, fitness)', async ({
    journalsWithData,
  }) => {
    const { page } = journalsWithData;

    const baseDate = {
      start: new Date().toISOString(),
      end: new Date().toISOString(),
    };

    // Create one journal per type so each type's edit drives the projection.
    const types: string[] = ['note', 'event', 'fitness'];
    for (const type of types) {
      const createResponse = await page.request.post('/api/journals', {
        headers: { 'Content-Type': 'application/vnd.api+json' },
        data: JSON.stringify({
          data: {
            type: 'journals',
            attributes: {
              title: `History ${type} ${Date.now()}`,
              content: `Content for ${type}`,
              event_date_range: baseDate,
              types: [type],
              type_data: {},
            },
          },
        }),
      });
      expect(createResponse.ok()).toBeTruthy();
      const created = await createResponse.json();
      const journalId: string = created.data.id;

      // Edit a base field; the change must appear in history for every type.
      const patchResponse = await page.request.patch(
        `/api/journals/${journalId}`,
        {
          headers: { 'Content-Type': 'application/json' },
          data: {
            data: {
              type: 'journals',
              id: journalId,
              attributes: { content: `Edited content for ${type}` },
            },
          },
        }
      );
      expect(patchResponse.ok()).toBeTruthy();

      await waitForHistoryEntry(
        page.request,
        journalId,
        attrs => attrs.field_name === 'content' && attrs.source === 'ui'
      );
    }
  });

  test('supports pagination in the journal history API', async ({
    journalsWithData,
  }) => {
    const { page, journals } = journalsWithData;
    const journal = journals[0];

    const historyResponse = await page.request.get(
      `/api/journals/${journal.id}/history?page=1&limit=5`
    );
    expect(historyResponse.ok()).toBeTruthy();

    const historyData = await historyResponse.json();

    // Verify JSON:API pagination metadata shape (mirrors the contact feed).
    expect(historyData).toHaveProperty('data');
    expect(historyData).toHaveProperty('meta');
    expect(historyData.meta).toHaveProperty('total_count');
    expect(historyData.meta).toHaveProperty('page_count');
    expect(historyData.meta.current_page).toBe(1);
    expect(historyData.meta.per_page).toBe(5);
    expect(Array.isArray(historyData.data)).toBe(true);
    expect(historyData.data.length).toBeLessThanOrEqual(5);
  });

  test('displays a provenance indicator and tooltip for an external source', async ({
    journalsWithData,
    isMobile,
  }) => {
    const { page, journals } = journalsWithData;
    const journal = journals[0];

    // Mock the history API to return a deterministic external-source entry so
    // the provenance icon/tooltip can be asserted without async projection.
    await page.route(`**/api/journals/${journal.id}/history*`, async route => {
      const json = {
        data: [
          {
            type: 'journal_history',
            id: '901',
            attributes: {
              entity_type: 'journal',
              entity_id: Number(journal.id),
              field_name: 'title',
              old_value: 'Old',
              new_value: 'New',
              changed_by: 'strava-sync',
              source: 'strava',
              created_at: new Date().toISOString(),
            },
          },
        ],
        meta: {
          total_count: 1,
          current_page: 1,
          page_count: 1,
          per_page: 10,
        },
      };
      await route.fulfill({ json });
    });

    await page.goto(`/journals/${journal.id}`);
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    const stravaTrigger = page.getByTestId('provenance-trigger-strava').first();
    await expect(stravaTrigger).toBeVisible();

    if (!isMobile) {
      await expect(async () => {
        await stravaTrigger.hover();
        await expect(page.getByRole('tooltip')).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 10000 });
    }
  });
});
