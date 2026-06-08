/**
 * E2E tests for the Immich PHOTO_ALBUM journal display (ITER11-004 Phase 2).
 *
 * PHOTO_ALBUM journals are integration-managed (created only by Immich album
 * sync), so these tests stub the journal detail response deterministically to
 * verify the journal edit/detail screen shows the album cover banner (clickable
 * to Immich) and the detected participant list.
 */

import { expect, test } from './fixtures';

// A 1×1 transparent PNG used as the stubbed album cover image.
const PNG_1X1 = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64'
);

const JOURNAL_ID = '987654';
const ALBUM_URL = 'https://immich.example.com/albums/album-abc';
const COVER_URL = `/api/journals/${JOURNAL_ID}/album-cover`;

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

const PHOTO_ALBUM_JOURNAL = {
  type: 'journals',
  id: JOURNAL_ID,
  attributes: {
    title: 'Summer Trip',
    content: 'Photos from the summer trip.',
    event_date_range: {
      start: '2026-01-15T00:00:00+00:00',
      end: '2026-01-17T23:59:59+00:00',
    },
    created_at: '2026-01-18T00:00:00+00:00',
    updated_at: '2026-01-18T00:00:00+00:00',
    types: ['photo_album'],
    type_data: {
      photo_album: {
        immich_album_id: 'album-abc',
        album_name: 'Summer Trip',
        album_url: ALBUM_URL,
        cover_url: COVER_URL,
        asset_count: 12,
      },
    },
    // Participants detected from photo people tags and resolved to contacts.
    contacts: [
      {
        id: '101',
        name: 'Alice Adams',
        first_name: 'Alice',
        last_name: 'Adams',
        relationship_type: 'PARTICIPANT',
        status: 'ATTENDED',
        photo_url: null,
      },
      {
        id: '102',
        name: 'Bob Brown',
        first_name: 'Bob',
        last_name: 'Brown',
        relationship_type: 'PARTICIPANT',
        status: 'ATTENDED',
        photo_url: null,
      },
    ],
    tags: [],
    calendar: null,
    children: [],
  },
};

async function setupAlbumJournalRoutes(page: import('@playwright/test').Page) {
  // The journal detail fetch — return our PHOTO_ALBUM journal.
  await page.route(`**/api/journals/${JOURNAL_ID}`, route => {
    if (route.request().method() !== 'GET') return route.fallback();
    return route.fulfill(json({ data: PHOTO_ALBUM_JOURNAL }));
  });

  // The on-demand album cover proxy — return a real image so the banner shows.
  await page.route(`**/api/journals/${JOURNAL_ID}/album-cover`, route =>
    route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: PNG_1X1,
    })
  );

  // External links for the journal — empty (not under test here).
  await page.route(`**/api/journals/${JOURNAL_ID}/external-links`, route =>
    route.fulfill(json({ data: [] }))
  );
}

test.describe('Immich PHOTO_ALBUM journal display', () => {
  test('shows the album cover banner and participant list', async ({
    authenticatedPage,
  }) => {
    await setupAlbumJournalRoutes(authenticatedPage);

    await authenticatedPage.goto(`/journals/${JOURNAL_ID}`);

    // The journal loads.
    await expect(
      authenticatedPage.getByTestId('journal-title-field')
    ).toBeVisible();

    // Participants (PARTICIPANT contacts) are listed on the journal.
    const contactBadges = authenticatedPage.getByTestId('contact-badges');
    await expect(contactBadges).toBeVisible();
    await expect(contactBadges).toContainText('Alice Adams');
    await expect(contactBadges).toContainText('Bob Brown');

    // Expand the Photo Album type section (collapsed by default).
    const albumToggle = authenticatedPage.getByTestId(
      'type-section-trigger-photo_album'
    );
    await expect(albumToggle).toBeVisible();
    await albumToggle.click();

    // The album cover banner is shown and points at the proxy endpoint.
    const banner = authenticatedPage.getByTestId('photo-album-cover');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('src', COVER_URL);

    // The banner is wrapped in a link that opens the album in Immich.
    const bannerLink = authenticatedPage.getByTestId('photo-album-cover-link');
    await expect(bannerLink).toHaveAttribute('href', ALBUM_URL);
    await expect(bannerLink).toHaveAttribute('target', '_blank');
  });
});
