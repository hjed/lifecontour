/**
 * E2E tests for ITER11-006 Phase 2: creating an Immich album from a journal's
 * date range.
 *
 * The journal itself is seeded for real via TestDataManager, but Immich data is
 * sync-derived and not seedable, so the Immich-backed endpoints (integration
 * status, photo search, album creation, thumbnail/cover proxies) and the
 * post-creation journal/external-links responses are stubbed with page.route —
 * the same convention used by the other Immich specs (immich-conflicts.spec.ts,
 * journal-detail.spec.ts). The real backend integration is covered by the
 * Phase 1 HTTP integration tests.
 */

import { expect, test } from './fixtures';
import { TestDataManager } from './data-management';

// 1x1 transparent PNG, used for the stubbed thumbnail and cover proxy images.
const PNG_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64'
);

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

const IMMICH_CONNECTED_INTEGRATION = {
  id: 'immich',
  type: 'integration',
  attributes: {
    name: 'Immich',
    status: 'connected',
    capabilities: ['contacts_sync', 'album_sync'],
    sync_summary: { last_sync_time: null, sync_count: 0, error_count: 0 },
    needs_reauth: false,
    needs_reconsent: false,
  },
};

const SEARCH_RESPONSE = {
  data: [
    {
      id: 'asset-1',
      type: 'immich-photo',
      attributes: {
        thumbnailUrl: '/api/integrations/immich/assets/asset-1/thumbnail',
        originalFileName: 'one.jpg',
        takenAt: '2024-01-15T10:00:00Z',
      },
    },
    {
      id: 'asset-2',
      type: 'immich-photo',
      attributes: {
        thumbnailUrl: '/api/integrations/immich/assets/asset-2/thumbnail',
        originalFileName: 'two.jpg',
        takenAt: '2024-01-15T11:00:00Z',
      },
    },
  ],
  meta: { count: 2 },
};

const CREATE_RESPONSE = {
  data: {
    id: 'album-uuid',
    type: 'immich-album',
    attributes: {
      journalId: 0,
      assetCount: 1,
      sharedLinkUrl: 'https://immich.example.com/share/tok',
    },
  },
};

const EXTERNAL_LINKS_RESPONSE = {
  data: [
    {
      type: 'external_links',
      id: 'immich_album-album-album-uuid',
      attributes: {
        source: 'immich_album',
        url: 'https://immich.example.com/albums/album-uuid',
        external_id: 'album-uuid',
      },
    },
    {
      type: 'external_links',
      id: 'immich_shared-shared-album-uuid',
      attributes: {
        source: 'immich_shared',
        url: 'https://immich.example.com/share/tok',
        external_id: 'album-uuid',
      },
    },
  ],
};

test.describe('Journal Album Creation (ITER11-006 Phase 2)', () => {
  test('search, deselect a photo, confirm, and see the album banner and links', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const today = new Date();
    const journals = await dataManager.createJournals([
      {
        title: 'Beach Day',
        content: 'A day at the beach',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
        types: ['note'],
      },
    ]);
    const journal = journals[0];
    const journalPath = `/api/journals/${journal.id}`;

    // Tracks the create-album transition: the journal + external-links stubs
    // return album data only after the album has been created.
    let albumCreated = false;

    // Immich connected.
    await page.route('**/api/integrations', route => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/integrations') return route.fallback();
      return route.fulfill(json({ data: [IMMICH_CONNECTED_INTEGRATION] }));
    });

    // Journal detail: inject the PHOTO_ALBUM type + data once the album exists,
    // preserving all real fields by editing the real backend response.
    await page.route(`**${journalPath}`, async route => {
      const url = new URL(route.request().url());
      if (url.pathname !== journalPath || route.request().method() !== 'GET') {
        return route.fallback();
      }
      const response = await route.fetch();
      const body = await response.json();
      if (albumCreated && body?.data?.attributes) {
        const attrs = body.data.attributes;
        attrs.types = Array.from(
          new Set([...(attrs.types ?? []), 'photo_album'])
        );
        attrs.type_data = {
          ...(attrs.type_data ?? {}),
          photo_album: {
            immich_album_id: 'album-uuid',
            album_name: 'Beach Day',
            album_url: 'https://immich.example.com/albums/album-uuid',
            asset_count: 1,
            cover_url: `${journalPath}/album-cover`,
          },
        };
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });

    // External links: empty before creation, album + shared link after.
    await page.route(`**${journalPath}/external-links`, route => {
      if (route.request().method() !== 'GET') return route.fallback();
      return route.fulfill(
        json(albumCreated ? EXTERNAL_LINKS_RESPONSE : { data: [] })
      );
    });

    // Cover + thumbnail proxies return a real image so the banner renders.
    await page.route(`**${journalPath}/album-cover`, route =>
      route.fulfill({ status: 200, contentType: 'image/png', body: PNG_BYTES })
    );
    await page.route('**/api/integrations/immich/assets/*/thumbnail', route =>
      route.fulfill({
        status: 200,
        contentType: 'image/png',
        body: PNG_BYTES,
      })
    );

    // Photo search.
    await page.route('**/api/integrations/immich/search-photos', route => {
      if (route.request().method() !== 'POST') return route.fallback();
      return route.fulfill(json(SEARCH_RESPONSE));
    });

    // Album creation flips the transition flag.
    await page.route('**/api/integrations/immich/create-album', route => {
      if (route.request().method() !== 'POST') return route.fallback();
      albumCreated = true;
      return route.fulfill(json(CREATE_RESPONSE));
    });

    await page.goto(journalPath.replace('/api', ''));
    await expect(page.getByTestId('journal-detail-view')).toBeVisible();

    // The button is visible and accessibly named.
    const button = page.getByTestId('create-album-button');
    await expect(button).toBeVisible();
    await expect(button).toHaveAccessibleName(/create album/i);

    // Click → search → dialog opens with both photos checked by default.
    await button.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAccessibleName(/create photo album/i);
    await expect(page.getByTestId('photo-checkbox-asset-1')).toBeChecked();
    await expect(page.getByTestId('photo-checkbox-asset-2')).toBeChecked();
    // Checkboxes are accessibly named by filename.
    await expect(
      page.getByRole('checkbox', { name: /include one\.jpg/i })
    ).toBeVisible();

    // Deselect a photo.
    await page.getByTestId('photo-checkbox-asset-2').click();
    await expect(page.getByTestId('photo-checkbox-asset-2')).not.toBeChecked();

    // Choose to create a public shared link.
    const sharedCheckbox = page.getByTestId('create-shared-link-checkbox');
    await expect(sharedCheckbox).toBeVisible();
    await sharedCheckbox.click();
    await expect(sharedCheckbox).toBeChecked();

    // Confirm → create-album request fires, then the dialog closes.
    const [createResponse] = await Promise.all([
      page.waitForResponse(resp =>
        resp.url().includes('/api/integrations/immich/create-album')
      ),
      page.getByTestId('create-album-confirm').click(),
    ]);
    expect(createResponse.ok()).toBeTruthy();
    await expect(dialog).toBeHidden();

    // Journal refreshes: external links appear (always-visible section).
    await expect(page.getByTestId('external-link-immich_album')).toBeVisible();
    await expect(page.getByTestId('external-link-immich_shared')).toBeVisible();

    // The PHOTO_ALBUM section now exists; expand it to reveal the cover banner.
    const albumSectionTrigger = page.getByTestId(
      'type-section-trigger-photo_album'
    );
    await expect(albumSectionTrigger).toBeVisible();
    await albumSectionTrigger.click();
    await expect(page.getByTestId('photo-album-cover')).toBeVisible();
  });
});
