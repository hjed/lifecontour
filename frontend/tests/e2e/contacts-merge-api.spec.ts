import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * API-level E2E coverage for the contact merge REST surface: per-field merge
 * overrides, and history re-pointing with the merge event surfacing in the
 * activity feed.
 *
 * The contract is exercised end-to-end against the running stack through the REST
 * surface. These tests drive the real HTTP path (auth cookie -> FastAPI -> service
 * -> PostgreSQL, plus the async outbox -> projection worker for the feed) using the
 * authenticated request context, asserting the merge outcome, the re-pointed audit
 * trail, and that the source contact is deleted.
 *
 * Deterministic data per the project's E2E rules — each test creates exactly the
 * contacts it needs with unique names and makes no conditional/skipped assertions.
 * The feed test polls the activity-history endpoint because projection is async
 * (a brief delay is acceptable per the activity-history spec).
 */

interface ContactAttributes {
  first_name: string;
  last_name?: string;
  middle_name?: string | null;
  nick_name?: string | null;
  company?: string | null;
  is_favourite?: boolean;
}

async function createContact(
  page: Page,
  attributes: ContactAttributes
): Promise<string> {
  const res = await page.request.post('/api/contacts', {
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify({
      data: {
        type: 'contacts',
        attributes: {
          contact_methods: [],
          addresses: [],
          notes: [],
          ...attributes,
        },
      },
    }),
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return String((await res.json()).data.id);
}

interface HistoryAttributes {
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  source: string;
}

async function getHistory(
  page: Page,
  contactId: string
): Promise<HistoryAttributes[]> {
  const res = await page.request.get(
    `/api/contacts/${contactId}/history?limit=100`
  );
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).data.map(
    (e: { attributes: HistoryAttributes }) => e.attributes
  );
}

async function updateField(
  page: Page,
  contactId: string,
  fieldName: string,
  value: string
): Promise<void> {
  const res = await page.request.patch(
    `/api/contacts/${contactId}/fields/${fieldName}`,
    {
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({
        data: { type: 'contact-field', attributes: { value } },
      }),
    }
  );
  expect(res.ok(), await res.text()).toBeTruthy();
}

test.describe('Contact merge overrides (API-level)', () => {
  test('applies per-field survivor / source / custom overrides and deletes the source', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now().toString();

    const survivorId = await createContact(page, {
      first_name: `Jane_${suffix}`,
      last_name: 'Survivor',
      nick_name: 'SurvivorNick',
      middle_name: 'SurvivorMiddle',
      company: 'SurvivorCo',
      is_favourite: true,
    });
    const sourceId = await createContact(page, {
      first_name: `Janet_${suffix}`,
      last_name: 'Source',
      nick_name: 'SourceNick',
      middle_name: 'SourceMiddle',
      company: 'SourceCo',
    });

    const mergeRes = await page.request.post(
      `/api/contacts/${survivorId}/merge`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify({
          data: {
            type: 'contact-merge',
            attributes: {
              source_contact_id: Number(sourceId),
              overrides: {
                nick_name: 'SourceNick', // take the source value
                middle_name: 'CustomMiddle', // supply a custom value
                is_favourite: false, // explicitly clear the favourite flag
              },
            },
          },
        }),
      }
    );
    expect(mergeRes.ok(), await mergeRes.text()).toBeTruthy();

    const attrs = (await mergeRes.json()).data.attributes;
    // last_name has no override -> survivor wins by default.
    expect(attrs.last_name).toBe('Survivor');
    // nick_name override picks the source's value over the survivor's.
    expect(attrs.nick_name).toBe('SourceNick');
    // middle_name override applies a custom value.
    expect(attrs.middle_name).toBe('CustomMiddle');
    // is_favourite override is honoured even though it is falsy.
    expect(attrs.is_favourite).toBe(false);

    // The source contact is deleted after a successful merge.
    const getSource = await page.request.get(`/api/contacts/${sourceId}`);
    expect(getSource.status()).toBe(404);
  });

  test('merges with no overrides (survivor-wins default) and deletes the source', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now().toString();

    const survivorId = await createContact(page, {
      first_name: `Keep_${suffix}`,
      last_name: 'Survivor',
      middle_name: null,
    });
    const sourceId = await createContact(page, {
      first_name: `Absorb_${suffix}`,
      last_name: 'Source',
      middle_name: 'FromSource',
    });

    const mergeRes = await page.request.post(
      `/api/contacts/${survivorId}/merge`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify({
          data: {
            type: 'contact-merge',
            attributes: { source_contact_id: Number(sourceId) },
          },
        }),
      }
    );
    expect(mergeRes.ok(), await mergeRes.text()).toBeTruthy();

    const attrs = (await mergeRes.json()).data.attributes;
    // Survivor identity wins where both differ.
    expect(attrs.last_name).toBe('Survivor');
    // Prefer-non-empty fills the survivor's empty middle_name from the source.
    expect(attrs.middle_name).toBe('FromSource');

    const getSource = await page.request.get(`/api/contacts/${sourceId}`);
    expect(getSource.status()).toBe(404);
  });
});

test.describe('Contact merge history re-pointing', () => {
  test('re-points the source history and surfaces the merge in the survivor feed', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const suffix = Date.now().toString();

    const survivorId = await createContact(page, {
      first_name: `Keeper_${suffix}`,
      last_name: 'Survivor',
    });
    const sourceId = await createContact(page, {
      first_name: `Absorbed_${suffix}`,
      last_name: 'Source',
    });

    // Generate a pre-merge change on the source so it has its own audit trail.
    const renamed = `Renamed_${suffix}`;
    await updateField(page, sourceId, 'first_name', renamed);

    // The activity feed is populated by the async projection worker; wait until
    // the source's change is visible before merging so the re-point is
    // deterministic (a brief delay is acceptable per the spec). An explicit
    // timeout/interval keeps this robust on slower CI than Playwright's default.
    await expect
      .poll(
        async () => {
          const history = await getHistory(page, sourceId);
          return history.some(
            e => e.field_name === 'first_name' && e.new_value === renamed
          );
        },
        { timeout: 30_000, intervals: [500, 1000, 2000] }
      )
      .toBe(true);

    const mergeRes = await page.request.post(
      `/api/contacts/${survivorId}/merge`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify({
          data: {
            type: 'contact-merge',
            attributes: { source_contact_id: Number(sourceId) },
          },
        }),
      }
    );
    expect(mergeRes.ok(), await mergeRes.text()).toBeTruthy();

    // The survivor's feed now carries BOTH the merge event (UI provenance,
    // referencing the source) and the source's re-pointed pre-merge change.
    await expect
      .poll(
        async () => {
          const history = await getHistory(page, survivorId);
          const hasMerge = history.some(
            e =>
              e.field_name === 'merged_from' &&
              e.source === 'ui' &&
              (e.old_value ?? '').includes(sourceId)
          );
          const hasRepointed = history.some(
            e => e.field_name === 'first_name' && e.new_value === renamed
          );
          return hasMerge && hasRepointed;
        },
        { timeout: 30_000, intervals: [500, 1000, 2000] }
      )
      .toBe(true);

    // The source contact is deleted after a successful merge.
    const getSource = await page.request.get(`/api/contacts/${sourceId}`);
    expect(getSource.status()).toBe(404);
  });
});
