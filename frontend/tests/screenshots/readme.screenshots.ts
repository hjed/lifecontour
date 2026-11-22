/**
 * README screenshots.
 *
 * Seeds a small, entirely fictional dataset and captures the key screens the
 * README's Features section shows into `docs/images/readme/`. Not a test: it
 * only waits for each screen to be ready before capturing it.
 *
 * Run from `frontend/` with `pnpm screenshots:readme` against the workspace
 * e2e stack (see the running-e2e-tests skill). It clears ALL contacts and
 * journals first, so never point it at a real instance.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';
import { expect, test } from '../e2e/fixtures';
import { TestDataManager, utcDayOffset } from '../e2e/data-management';
import { selectCalendarView } from '../e2e/utils/calendar-view';

const OUTPUT_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../docs/images/readme'
);

type Theme = 'light' | 'dark';

const VIEWPORT = { width: 1440, height: 900 };

/** A canyon descent near Sydney, a few points so the map draws a line. */
const CANYON_GPX = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Lifecontour README">
  <trk>
    <name>Grand Canyon loop</name>
    <trkseg>
      <trkpt lat="-33.6603" lon="150.3046"><ele>1010</ele></trkpt>
      <trkpt lat="-33.6618" lon="150.3071"><ele>960</ele></trkpt>
      <trkpt lat="-33.6639" lon="150.3093"><ele>890</ele></trkpt>
      <trkpt lat="-33.6655" lon="150.3122"><ele>840</ele></trkpt>
      <trkpt lat="-33.6668" lon="150.3160"><ele>815</ele></trkpt>
      <trkpt lat="-33.6649" lon="150.3194"><ele>870</ele></trkpt>
      <trkpt lat="-33.6627" lon="150.3171"><ele>950</ele></trkpt>
      <trkpt lat="-33.6608" lon="150.3132"><ele>1005</ele></trkpt>
    </trkseg>
  </trk>
</gpx>`;

/** A month and day `days` from today (UTC), for an upcoming important date. */
function monthDayFromNow(days: number): { month: number; day: number } {
  const date = new Date(utcDayOffset(days));
  return { month: date.getUTCMonth() + 1, day: date.getUTCDate() };
}

function at(days: number, hour: number): { start: string; end: string } {
  return { start: utcDayOffset(days, hour), end: utcDayOffset(days, hour + 1) };
}

const DAILY_SUMMARY =
  'A sociable Sunday: a project kickoff with Jordan, and a quiet morning ' +
  'reflection after dinner with Alex and Sam last night.';

/**
 * The e2e stack stubs the AI model, so its daily summary says as much.
 * Swap that one sentence for a believable one on the way to the page — both
 * the journals list and the home dashboard carry it.
 */
async function replaceStubbedDailySummary(page: Page): Promise<void> {
  const carriesSummary = (url: URL): boolean =>
    url.pathname.startsWith('/api/journals/daily-summary/') ||
    url.pathname === '/api/home-dashboard';
  await page.route(carriesSummary, async route => {
    const response = await route.fetch();
    const body = (await response.text()).replace(
      /A stubbed daily summary:[^"]*/g,
      DAILY_SUMMARY
    );
    await route.fulfill({ response, body });
  });
}

/**
 * Hide dev-only chrome (`next dev` runs locally): the React Query Devtools
 * toggle and the Next.js dev indicator.
 */
async function hideDevChrome(page: Page): Promise<void> {
  await page.addStyleTag({
    content: `
      .tsqd-parent-container, .tsqd-open-btn-container, nextjs-portal {
        display: none !important;
      }
    `,
  });
}

const JOURNAL_TAGS = ['Friends', 'Outdoors', 'Work'];
const GEAR_ITEMS = ['Static rope 60m'];
const TEMPLATES = ['Empress Falls'];
const CALENDARS = ['Personal'];

/**
 * Journal tags and gear items need unique names and outlive the journal
 * purge, so remove any a previous (perhaps interrupted) run left behind.
 */
async function deleteLeftovers(
  page: Page,
  collection: string,
  names: string[]
): Promise<void> {
  const response = await page.request.get(collection);
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as {
    data: Array<{ id: string; attributes: { name: string } }>;
  };
  for (const item of body.data) {
    if (names.includes(item.attributes.name)) {
      const deleted = await page.request.delete(`${collection}/${item.id}`);
      expect(deleted.ok()).toBe(true);
    }
  }
}

async function capture(
  page: Page,
  url: string,
  theme: Theme,
  file: string,
  ready: (page: Page) => Promise<void>
): Promise<void> {
  await page.setViewportSize(VIEWPORT);
  await page.emulateMedia({ colorScheme: theme });
  await page.goto(url);
  await ready(page);
  await hideDevChrome(page);
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0);
  await page.screenshot({ path: path.join(OUTPUT_DIR, file) });
}

test('capture README screenshots', async ({ authenticatedPage: page }) => {
  test.setTimeout(5 * 60 * 1000);
  const data = new TestDataManager(page);
  await replaceStubbedDailySummary(page);
  await data.clearAllJournals();
  await data.clearAllContacts();
  await deleteLeftovers(page, '/api/journals/tags', JOURNAL_TAGS);
  await deleteLeftovers(page, '/api/gear-items', GEAR_ITEMS);
  await deleteLeftovers(page, '/api/templates', TEMPLATES);
  await deleteLeftovers(page, '/api/calendars', CALENDARS);

  // People
  const [alex, sam, priya, jordan] = await data.createContacts([
    {
      firstName: 'Alex',
      lastName: 'Rivera',
      exactName: true,
      isFavourite: true,
      importantDates: [
        {
          date_type: 'birthday',
          precision: 'full',
          year: 1991,
          ...monthDayFromNow(4),
        },
        {
          date_type: 'first_met',
          precision: 'full',
          year: 2014,
          month: 3,
          day: 8,
        },
      ],
    },
    { firstName: 'Sam', lastName: 'Okafor', exactName: true },
    {
      firstName: 'Priya',
      lastName: 'Natarajan',
      exactName: true,
      isFavourite: true,
    },
    { firstName: 'Jordan', lastName: 'Lee', exactName: true },
  ]);
  await data.createRelationship(alex.id, sam.id, 'partner');
  await data.createRelationship(alex.id, jordan.id, 'colleague');
  await data.createUserRelationship(alex.id, 'friend');
  await data.createUserRelationship(priya.id, 'family');
  // The e2e stack has no AI model, so give Alex a written summary instead.
  const summary = await page.request.patch(`/api/contacts/${alex.id}/summary`, {
    data: {
      data: {
        user_override_text:
          'Close friend since uni and regular canyoning partner. Recently ' +
          'started a new job; partner Sam is training for the City2Surf.',
      },
    },
  });
  expect(summary.ok()).toBe(true);

  // Journal tags
  const [friends, outdoors, work] = await data.createJournalTags([
    { name: 'Friends', color: '#10B981', exactName: true },
    { name: 'Outdoors', color: '#F59E0B', exactName: true },
    { name: 'Work', color: '#6366F1', exactName: true },
  ]);

  // Journals
  const dinner = await data.createJournal({
    title: 'Dinner at Alex and Sam’s',
    exactTitle: true,
    content:
      'Alex cooked a huge laksa. Sam is training for the **City2Surf** and ' +
      'Alex has just started a new role.\n\n' +
      '- Lend Sam the foam roller\n- Ask about the new job next time',
    event_date_range: at(-1, 8),
    contacts: [
      { contact_id: alex.id, relationship_type: 'PARTICIPANT' },
      { contact_id: sam.id, relationship_type: 'PARTICIPANT' },
    ],
  });
  await data.assignTagsToJournal(dinner.id, [friends.id]);

  const standup = await data.createJournal({
    title: 'Project kickoff with Jordan',
    exactTitle: true,
    content: 'Agreed the scope for the spring release.',
    event_date_range: at(0, 0),
    contacts: [{ contact_id: jordan.id, relationship_type: 'PARTICIPANT' }],
  });
  await data.assignTagsToJournal(standup.id, [work.id]);

  await data.createJournal({
    title: 'Morning reflection',
    exactTitle: true,
    content: 'Slept well. Feeling ready for the week.',
    event_date_range: at(0, 21),
  });

  const lunch = await data.createJournal({
    title: 'Lunch with Priya',
    exactTitle: true,
    content: 'Caught up on family news and planned the winter trip.',
    event_date_range: at(-3, 2),
    contacts: [{ contact_id: priya.id, relationship_type: 'PARTICIPANT' }],
  });
  await data.assignTagsToJournal(lunch.id, [friends.id]);

  // Adventures
  const canyon = await data.createJournal({
    title: 'Grand Canyon, Blue Mountains',
    exactTitle: true,
    content:
      'Classic loop with Alex. Cold water in the tunnel section, ' +
      'great light on the walk out.',
    event_date_range: at(-6, 22),
    types: ['canyoning', 'fitness'],
    type_data: {
      fitness: { distance: 6200, elevation_gain: 410, duration: 15300 },
    },
    contacts: [{ contact_id: alex.id, relationship_type: 'PARTICIPANT' }],
  });
  await data.assignTagsToJournal(canyon.id, [outdoors.id]);
  await data.createRoute(canyon.id, {
    name: 'Grand Canyon loop',
    gpx_data: CANYON_GPX,
  });

  await data.createJournal({
    title: 'Six Foot Track, day one',
    exactTitle: true,
    content: 'Katoomba to the Old Ford Reserve.',
    event_date_range: at(-20, 21),
    types: ['bushwalking'],
  });
  await data.createJournal({
    title: 'Winter trip planning',
    exactTitle: true,
    content: 'Routes, permits and gear list for the Kosciuszko trip.',
    event_date_range: at(9, 8),
    types: ['outdoor_planning'],
    contacts: [{ contact_id: priya.id, relationship_type: 'PARTICIPANT' }],
  });
  await data.createJournal({
    title: 'Claustral Canyon',
    exactTitle: true,
    content: 'Abseils and swims; wetsuits essential.',
    event_date_range: at(14, 21),
    types: ['canyoning'],
  });
  const empress = await data.createTemplate('Empress Falls', 'canyoning', {
    exactName: true,
  });
  await data.createJournal({
    title: 'Empress Falls with Priya',
    exactTitle: true,
    content: 'Quick morning trip; the falls were running well.',
    event_date_range: at(-12, 22),
    types: ['abseiling_trip'],
    type_data: { abseiling_trip: { template_id: empress.id } },
    contacts: [{ contact_id: priya.id, relationship_type: 'PARTICIPANT' }],
  });
  const rope = await data.createGearItem('Static rope 60m', {
    exactName: true,
  });
  await data.createJournal({
    title: 'Rope out for the season',
    exactTitle: true,
    content: 'Borrowed from the club store.',
    event_date_range: { start: utcDayOffset(-1), end: utcDayOffset(1) },
    types: ['gear_usage'],
    type_data: { gear_usage: { items: [{ gear_item_id: rope.id }] } },
  });

  // Today's agenda
  const [personal] = await data.createCalendars([
    { name: 'Personal', color: '#0EA5E9' },
  ]);
  await data.createJournal({
    title: 'Climbing at the gym with Sam',
    exactTitle: true,
    content: 'Bouldering session after work.',
    event_date_range: at(0, 7),
    types: ['event'],
    type_data: {
      event: {
        calendar_id: personal.id,
        is_all_day: false,
        sync_invitees: false,
      },
    },
    contacts: [{ contact_id: sam.id, relationship_type: 'PARTICIPANT' }],
  });

  // Tasks, anchored to the journals they came from
  const catchUp = await data.createJournal({
    title: 'Coffee with Alex',
    exactTitle: true,
    content: 'Follow-up catch up.',
    event_date_range: at(3, 22),
    contacts: [{ contact_id: alex.id, relationship_type: 'PARTICIPANT' }],
  });
  await data.createTask({
    creatingJournalId: dinner.id,
    dueJournalId: catchUp.id,
    text: 'Lend Sam the foam roller',
    contactIds: [sam.id],
  });
  await data.createTask({
    creatingJournalId: dinner.id,
    dueJournalId: catchUp.id,
    text: 'Ask Alex how the new job is going',
    contactIds: [alex.id],
  });

  // Screens — alternating light and dark mode
  await capture(page, '/', 'light', 'home-dashboard.png', async p => {
    await expect(p.getByTestId('home-dashboard-ready')).toBeVisible();
    // That marks only the shell: each section loads on its own, and the
    // summary card drops its skeleton while the summary is still generating.
    // Wait for the content every section is meant to show.
    await expect(p.getByText(DAILY_SUMMARY)).toBeVisible();
    await expect(p.getByText('Climbing at the gym with Sam')).toBeVisible();
    await expect(p.getByText('Lend Sam the foam roller')).toBeVisible();
    await expect(p.getByText(/Birthday · turns/)).toBeVisible();
  });

  await capture(
    page,
    `/journals/${dinner.id}`,
    'dark',
    'journal-entry.png',
    async p => {
      await expect(p.getByTestId('journal-title-field')).toBeVisible();
    }
  );

  await capture(page, '/journals', 'light', 'journals.png', async p => {
    await expect(p.getByTestId('journals-list-ready')).toBeVisible();
    await selectCalendarView(p, 'Month');
    await p.getByRole('button', { name: 'Hide Filters' }).click();
    // Wait on a journal dated today: the month grid always contains today,
    // while entries seeded days away can fall outside it near a month's end.
    await expect(
      p
        .getByTestId('calendar-month-view')
        .getByText('Project kickoff with Jordan')
    ).toBeVisible();
    // Tall enough for the whole month, so nothing scrolls under the header.
    await p.setViewportSize({ width: 1440, height: 1100 });
    await p.evaluate(() => window.scrollTo(0, 0));
  });

  await capture(
    page,
    `/contacts/${alex.id}`,
    'dark',
    'contact.png',
    async p => {
      await expect(p.getByText(/^partner$/i)).toBeVisible();
      await expect(p.getByText('Close friend since uni')).toBeVisible();
    }
  );

  await capture(
    page,
    '/journals/outdoor-logbook',
    'light',
    'outdoor-logbook.png',
    async p => {
      await expect(p.getByTestId('logbook-stats-ready')).toBeVisible();
      await expect(p.getByTestId('totals-ready')).toBeVisible();
    }
  );

  await capture(
    page,
    `/journals/${canyon.id}`,
    'dark',
    'adventure-route.png',
    async p => {
      await expect(p.getByTestId('journal-title-field')).toBeVisible();
      await p.getByTestId('type-section-trigger-fitness').click();
      await expect(p.getByTestId('journal-routes-editor')).toContainText(
        'Grand Canyon loop'
      );
      // The app header is translucent, so show the whole entry down to the
      // map in one unscrolled view rather than scrolling under the header.
      await p.setViewportSize({ width: 1440, height: 1340 });
      await p.evaluate(() => window.scrollTo(0, 0));
      // Settled map: the fit-to-route zoom has finished, the previous zoom
      // level's tiles are pruned, and every tile of the final level is drawn.
      const map = p.locator('.leaflet-container');
      await expect(map).not.toHaveClass(/leaflet-zoom-anim/);
      await expect(map.locator('.leaflet-tile-container')).toHaveCount(1);
      await expect(map.locator('.leaflet-tile-loaded').first()).toBeVisible();
      await expect(
        map.locator('.leaflet-tile:not(.leaflet-tile-loaded)')
      ).toHaveCount(0);
      // Tiles fade in once loaded; wait until they are fully opaque.
      await expect
        .poll(() =>
          map
            .locator('.leaflet-tile')
            .evaluateAll(tiles =>
              tiles.every(tile => getComputedStyle(tile).opacity === '1')
            )
        )
        .toBe(true);
    }
  );
});
