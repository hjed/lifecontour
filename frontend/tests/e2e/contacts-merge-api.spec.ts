import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * API-level E2E coverage for ITER13-002 Phase 1 (per-field merge overrides).
 *
 * The merge UI lands in ITER13-003; until then the override contract is exercised
 * end-to-end against the running stack through the REST surface. These tests drive
 * the real HTTP path (auth cookie -> FastAPI -> service -> PostgreSQL) using the
 * authenticated request context, asserting the survivor reflects the chosen
 * survivor / source / custom values and the source contact is deleted.
 *
 * Deterministic data per the project's E2E rules — each test creates exactly the
 * contacts it needs with unique names and makes no conditional/skipped assertions.
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
