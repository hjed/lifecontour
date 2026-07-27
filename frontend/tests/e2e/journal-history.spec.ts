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
import { TestDataManager } from './data-management';

type HistoryAttributes = {
  field_name: string;
  source: string;
  old_value: string | null;
  new_value: string | null;
};

/**
 * Poll the journal history API until an entry matches EVERY predicate.
 *
 * Multiple predicates share one polling window on purpose: entries produced by a
 * single user action almost always project in the same relay batch, so waiting
 * for them separately would both re-fetch the same list and split the retry
 * budget across independent timeouts.
 */
async function waitForHistoryEntries(
  request: import('@playwright/test').APIRequestContext,
  journalId: string,
  ...predicates: ((attrs: HistoryAttributes) => boolean)[]
): Promise<void> {
  // With no predicates there is nothing to be unmatched, so the poll would pass on
  // its first attempt and the caller would assert nothing at all. Fail loudly
  // instead of silently going green.
  expect(
    predicates.length,
    'waitForHistoryEntries needs at least one predicate'
  ).toBeGreaterThan(0);

  await expect(async () => {
    const response = await request.get(`/api/journals/${journalId}/history`);
    expect(response.ok()).toBeTruthy();
    const json = await response.json();
    expect(Array.isArray(json.data)).toBe(true);
    const entries = json.data.map(
      (entry: { attributes: HistoryAttributes }) => entry.attributes
    );
    const unmatched = predicates.filter(
      matches => !entries.some((attrs: HistoryAttributes) => matches(attrs))
    );
    expect(unmatched).toHaveLength(0);
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
    await waitForHistoryEntries(
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

      await waitForHistoryEntries(
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

  /**
   * ITER17-005 Phase 1: journal tag changes are domain events, so they reach the
   * same feed as any other field change.
   *
   * The tag is created through `TestDataManager` and every assertion keys off its
   * id and its UUID-suffixed name — the journal tag namespace is global and shared
   * with parallel workers, so "a tag exists" would not be deterministic. The
   * add/remove go through the real editor rather than the API so the test covers
   * the path a user actually takes.
   */
  test('records tag assignment and removal in the journal activity feed', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    // Registered before anything is created, not after: the manager cleans up
    // whatever it has tracked so far, so an exception part-way through setup still
    // removes the tag. Journal tags are a globally shared namespace, so a leaked
    // one outlives this test and accumulates for every other worker.
    testCleanup(async () => await dataManager.cleanup());

    const [tag] = await dataManager.createJournalTags([
      { name: 'HistoryTag', color: '#38A169' },
    ]);
    const journal = await dataManager.createJournal({
      title: 'Tag History Subject',
      content: 'Its tag changes must appear in the activity feed.',
      event_date_range: {
        start: '2026-01-18T10:00:00Z',
        end: '2026-01-18T10:30:00Z',
      },
      types: ['note'],
    });

    await page.goto(`/journals/${journal.id}`);
    const tagsEditor = page.getByTestId('journal-tags-editor');
    await expect(tagsEditor).toBeVisible();

    // Assign the tag through the editor's search popover.
    await tagsEditor.getByTestId('add-tag-button').click();
    await page.getByTestId('tag-search-input').fill(tag.name);
    await page.getByTestId(`tag-option-${tag.id}`).click();

    const tagBadge = tagsEditor.getByTestId(`tag-badge-${tag.id}`);
    await expect(tagBadge).toBeVisible({ timeout: 10000 });

    // Remove it again via the badge's accessible remove control. Removal is not
    // optimistic (the badge waits for the DELETE plus a refetch), so wait on the
    // DELETE itself rather than retrying the click: a retry would need a
    // conditional on the badge's transient visibility, and its second click would
    // issue a second DELETE that only the removal's own no-op guard makes safe.
    const removeButton = tagsEditor.getByRole('button', {
      name: `Remove tag ${tag.name}`,
    });
    await expect(removeButton).toBeVisible();

    const [removeResponse] = await Promise.all([
      page.waitForResponse(
        response =>
          new URL(response.url()).pathname ===
            `/api/journals/${journal.id}/relationships/tags/${tag.id}` &&
          response.request().method() === 'DELETE'
      ),
      removeButton.click(),
    ]);
    expect(removeResponse.ok()).toBeTruthy();
    await expect(tagBadge).toBeHidden({ timeout: 15000 });

    // Both changes travel through the async projection before they are readable.
    await waitForHistoryEntries(
      page.request,
      journal.id,
      attrs =>
        attrs.field_name === 'tags' &&
        attrs.source === 'ui' &&
        attrs.new_value === tag.name,
      attrs =>
        attrs.field_name === 'tags' &&
        attrs.source === 'ui' &&
        attrs.old_value === tag.name
    );

    // A fresh load renders both entries in the feed at the bottom of the page
    // (the history query stays fresh for two minutes, so it will not refetch on
    // its own after the projection lands).
    await page.goto(`/journals/${journal.id}`);
    await expect(page.getByRole('heading', { name: /Activity/i })).toBeVisible({
      timeout: 10000,
    });

    // Provenance is asserted on the tag rows themselves, not anywhere in the feed:
    // a freshly-created journal always carries a `ui`-sourced `__created__` entry,
    // so an unscoped `provenance-trigger-ui` would be visible even if the tag
    // events had projected with the wrong source. Each row is also asserted to
    // appear exactly once, which would catch a duplicated projection.
    const feed = page.getByTestId('activity-feed');
    const tagRow = (description: string) =>
      feed
        .locator('[data-testid^="activity-item-"]')
        .filter({ hasText: description });

    for (const description of [
      `Added Tags: "${tag.name}"`,
      `Removed Tags: "${tag.name}"`,
    ]) {
      const row = tagRow(description);
      await expect(row).toHaveCount(1, { timeout: 10000 });
      await expect(row.getByTestId('provenance-trigger-ui')).toBeVisible();
    }
  });
});
