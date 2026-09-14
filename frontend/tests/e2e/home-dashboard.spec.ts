import type { Locator, Page } from '@playwright/test';
import type {
  DashboardSection,
  DashboardSectionStatus,
  DashboardSummaryState,
  HomeDashboardAgendaEntry,
  HomeDashboardAttributes,
  HomeDashboardResponse,
  HomeDashboardSummary,
  HomeDashboardTask,
  HomeDashboardTasks,
  HomeDashboardUpcomingDate,
  HomeDashboardUpcomingDates,
} from '../../src/lib/api/home-dashboard';
import type { ImportantDateTypeEnum } from '../../src/types/contacts';
import type { DailySummaryResponse } from '../../src/types/journals';
import { TestDataManager } from './data-management';
import {
  test,
  expect,
  type TestContact,
  type TestJournal,
  type TestTask,
} from './fixtures';

/**
 * Home Dashboard — page shell (ITER18-004 Phase 3)
 *
 * The structural wireframe facts this phase is responsible for: the page frame
 * (**W1**, **W2**), the three evidence sections in their grid (**W3**, **W4**),
 * the retirement of the placeholder card grid, and the primary-navigation entry
 * that makes the dashboard a destination (wireframe gap 4).
 *
 * The sections' contents — ordering, caps, the tomorrow disclosure, the summary
 * states — belong to the phases that build them and are not asserted here.
 *
 * No fixture data is created: the shell is the same whatever the user's data,
 * and every assertion below holds for an empty account and a full one alike.
 * The one value that varies is the day, and the tests read it from the API
 * rather than from a clock, which is the point of one of them.
 */

/** Wireframe order (**W3**), which is also the below-`lg` stacking order. */
const SECTION_NAMES = ['Agenda', 'Tasks', 'Upcoming dates'] as const;

/**
 * All four sections in wireframe order — the summary headline (**W5**) over
 * the three evidence sections (**W3**) — each with the card its visible title
 * is drawn in.
 */
const ALL_SECTIONS = [
  { name: 'AI Daily Summary', cardTestId: 'dashboard-summary-card' },
  { name: 'Agenda', cardTestId: 'agenda-card' },
  { name: 'Tasks', cardTestId: 'tasks-card' },
  { name: 'Upcoming dates', cardTestId: 'upcoming-dates-card' },
] as const;

/** Every card the placeholder home page used to render. */
const RETIRED_PLACEHOLDER_TEXT = [
  'Personal Management System',
  'Your personal CRM and journal with AI integration',
  'Sync with Google Calendar and link events to photos and journal entries.',
  'Connect with Immich to link photos to contacts, events, and journal entries.',
  'MCP protocol support for AI assistants to access and manage your data.',
  'Monitor system health and integration status.',
] as const;

const DESKTOP = { width: 1280, height: 900 };
const MOBILE = { width: 375, height: 667 };

/**
 * Open the dashboard and wait for its shell — and for every section to have
 * *answered*, which is not the same thing and is not "wait for the network".
 *
 * The shell renders immediately and the sections fill in behind it, so a test
 * that measures geometry the moment the shell appears is measuring a page that
 * is still moving. That was survivable while a pending section drew a single
 * muted line, and stopped being so when ITER18-004 Phase 16 gave it a skeleton:
 * the summary's placeholder is now three bars tall rather than one line, so the
 * grid beneath it drops ~44px when the real summary arrives. `sectionBoxes`
 * reads its three boxes one after another, and a shift landing between two of
 * them made the three columns look misaligned — which is how CI caught it on
 * `Mobile Chrome` while every other project's timing hid it.
 *
 * Waiting for the loading states to clear costs nothing: they are gone the
 * moment the one dashboard request resolves, whatever it says.
 */
async function openDashboard(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('home-dashboard-ready')).toBeVisible();

  for (const loading of [
    'dashboard-summary-loading',
    'agenda-loading',
    'tasks-loading',
    'upcoming-dates-loading',
  ]) {
    await expect(page.getByTestId(loading)).toHaveCount(0);
  }
}

/**
 * The three evidence sections.
 *
 * Scoped to the grid rather than the page: the app chrome contributes a region
 * of its own (the toast notification area), so an unscoped role query would
 * count four.
 */
function sections(page: Page) {
  return page.getByTestId('dashboard-sections').getByRole('region');
}

/** The three sections' bounding boxes, in DOM order. */
async function sectionBoxes(page: Page) {
  const boxes = [];
  for (const [index] of SECTION_NAMES.entries()) {
    const box = await sections(page).nth(index).boundingBox();
    expect(box).not.toBeNull();
    boxes.push(box!);
  }
  return boxes;
}

/**
 * The full localised date the header should carry for a given anchor day
 * (**W2**): weekday, then day before month, en-AU throughout.
 */
function expectedAnchorLabel(anchorDate: string): string {
  const [year, month, day] = anchorDate.split('-').map(Number);
  const asDate = new Date(Date.UTC(year, month - 1, day));
  const named = (options: Intl.DateTimeFormatOptions) =>
    asDate.toLocaleDateString('en-AU', { ...options, timeZone: 'UTC' });

  return `${named({ weekday: 'long' })}, ${day} ${named({ month: 'long' })} ${year}`;
}

test.describe('Home Dashboard — page shell', () => {
  test.describe('The page frame', () => {
    // Note: the Today heading and framing line are unit-tested in
    // DashboardPageHeader.test.tsx, and the root-route landing is covered by
    // 'is the view an authenticated user lands on at the root' below. The
    // anchor-day test stays as e2e because it reads the real server-side
    // anchor from the API, which a unit test can only mock.

    test('labels the page with the day the server anchored it on', async ({
      authenticatedPage: page,
    }) => {
      // The dashboard takes no date parameters: every window is anchored on
      // today in the user's configured timezone, server-side, and `meta.anchor`
      // is what a surface must label the page with. Reading the anchor from the
      // API rather than from a clock is what makes this deterministic — and
      // what would catch a header that used the browser's today instead.
      const response = await page.request.get('/api/home-dashboard');
      expect(response.ok()).toBe(true);
      const anchorDate = (await response.json()).meta.anchor.date as string;

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(page.getByTestId('dashboard-anchor-date')).toHaveText(
        expectedAnchorLabel(anchorDate)
      );
    });
  });

  test.describe('The three evidence sections', () => {
    // Note: each section's labelled list, wireframe title/description, and
    // empty line are unit-tested in DashboardSection.test.tsx,
    // DashboardSectionCard.test.tsx, and section-cards.test.tsx. What stays
    // here is the page-level composition: all three sections mounted together,
    // in wireframe order.

    test('renders them in wireframe order, each a labelled region', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const regions = sections(page);
      await expect(regions).toHaveCount(SECTION_NAMES.length);

      for (const [index, name] of SECTION_NAMES.entries()) {
        await expect(regions.nth(index)).toHaveAccessibleName(name);
      }
    });
  });

  test.describe('All four sections (W3, W4, W5)', () => {
    /**
     * ITER18-004 Phase 17's first structural fact: the summary over the three
     * evidence sections, in wireframe order, each under its heading.
     *
     * Scoped to the page body rather than the grid the test above uses, because
     * the summary is not in the grid and its place among the sections is the
     * question. The tomorrow disclosure's panel is a region too, but collapsed
     * it is `hidden` and so out of the accessibility tree (see Phase 8's note),
     * which is why four is the right count on arrival.
     *
     * No fixtures and no mock: the summary's heading lives in the frame every
     * one of its states shares, so the structure is the same whatever the
     * account holds.
     */
    test('renders the four sections in wireframe order, each under its heading', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const regions = page
        .getByTestId('home-dashboard-ready')
        .getByRole('region');
      await expect(regions).toHaveCount(ALL_SECTIONS.length);

      for (const [index, section] of ALL_SECTIONS.entries()) {
        const region = regions.nth(index);
        await expect(region).toHaveAccessibleName(section.name);
        // The level-2 heading the region is labelled by (W4) — visually
        // hidden on the three evidence sections, whose visible title is the
        // card's own, asserted next.
        await expect(
          region.getByRole('heading', { level: 2, name: section.name })
        ).toHaveCount(1);
        await expect(
          region
            .getByTestId(section.cardTestId)
            .getByText(section.name, { exact: true })
        ).toBeVisible();
      }
    });
  });

  test.describe('The retired placeholder', () => {
    test('renders none of the six placeholder cards', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      for (const text of RETIRED_PLACEHOLDER_TEXT) {
        await expect(page.getByText(text, { exact: true })).toHaveCount(0);
      }
    });
  });

  test.describe('Primary navigation', () => {
    test('reaches the dashboard from the sidebar and marks it current', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await page.goto('/contacts');

      const homeLink = page.getByTestId('nav-link-home');
      await expect(homeLink).toBeVisible();
      // Away from the dashboard, Home is not the current page — the case a
      // prefix match on '/' would get wrong on every route in the app.
      await expect(homeLink).not.toHaveAttribute('aria-current', 'page');

      await homeLink.click();

      await expect(page.getByTestId('home-dashboard-ready')).toBeVisible();
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByTestId('nav-link-home')).toHaveAttribute(
        'aria-current',
        'page'
      );
    });

    test('is the view an authenticated user lands on at the root', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(page).not.toHaveURL(/\/auth\/login/);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Today');
    });
  });

  test.describe('Layout', () => {
    test('sits three across on a wide viewport, sized independently', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const [agenda, tasks, dates] = await sectionBoxes(page);

      // One row: same top edge, left to right in wireframe order.
      expect(agenda.y).toBeCloseTo(tasks.y, 0);
      expect(tasks.y).toBeCloseTo(dates.y, 0);
      expect(tasks.x).toBeGreaterThan(agenda.x);
      expect(dates.x).toBeGreaterThan(tasks.x);
    });

    test('stacks into one column on a narrow viewport, in wireframe order', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(MOBILE);
      await openDashboard(page);

      const [agenda, tasks, dates] = await sectionBoxes(page);

      expect(tasks.x).toBeCloseTo(agenda.x, 0);
      expect(dates.x).toBeCloseTo(agenda.x, 0);
      expect(tasks.y).toBeGreaterThan(agenda.y);
      expect(dates.y).toBeGreaterThan(tasks.y);
    });

    test('has no horizontal overflow at mobile width', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(MOBILE);
      await openDashboard(page);

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));

      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    });
  });
});

/**
 * Home Dashboard — the AI daily summary card (ITER18-004 Phase 4)
 *
 * **W5**–**W10**: the headline card, its three states, its key-stats footer and
 * the Regenerate control that sits outside all three state branches.
 *
 * The dashboard payload is route-mocked here rather than driven from fixtures,
 * and deliberately so. The e2e stack's model is a stub
 * (`ENABLE_TEST_DAILY_SUMMARY_STUB`), so `generated` *can* be created — the
 * *generated end to end* block at the foot of this file does — but today's
 * summary is one row shared by the whole run, and `generating` is transient by
 * nature. Each test here installs its own mock for exactly one state before
 * navigating, which is what keeps every assertion single-outcome;
 * `journals-daily-summary.spec.ts` sets the same precedent for the journals
 * view's copy of this card.
 *
 * `unavailable` is served for the same reason: whether the anchor day has a
 * summary row depends on what else the run has done, so an unmocked test would
 * pass or fail on suite ordering rather than on this card. Serving it keeps the
 * state under the test's own control. Proving the real endpoint reaches this rendering is the
 * backend's 69 unit and integration tests plus ITER18-005 Phase 8's e2e, which
 * owns the summary end to end.
 */

const SUMMARY_TIMEZONE = 'Australia/Sydney';

/**
 * The anchor every test here serves: **today in the fixture's zone**.
 *
 * Not a fixed past day. The card refuses to regenerate a day its anchor has
 * outlived — a dashboard held open across local midnight would otherwise
 * rewrite yesterday's summary under a page headed "Today" — so a past anchor
 * would leave **W6**'s control disabled in every test rather than exercised.
 * Derived through `Intl` in the same zone the payload names, so the fixture and
 * the card agree by construction rather than by coincidence.
 */
const SUMMARY_ANCHOR = new Intl.DateTimeFormat('en-CA', {
  timeZone: SUMMARY_TIMEZONE,
}).format(new Date());
/**
 * The calendar day after `day`, as `YYYY-MM-DD`.
 *
 * Stepped in UTC because the e2e user has no configured timezone, so the
 * backend's day boundaries — and therefore `agenda.tomorrow.date` — are UTC.
 * Built from the anchor the API gave rather than from a clock, for the reason
 * {@link anchorDay} exists.
 *
 * Declared here, above the module-scope constant that calls it: as a hoisted
 * `function` the order happens not to matter, but rewriting it as a `const`
 * arrow — a routine tidy-up — would throw at module evaluation and fail all
 * 57 tests in this file with an error pointing nowhere near the change.
 */
function nextDay(day: string): string {
  return daysAfter(day, 1);
}

/**
 * The calendar day `count` days after `day`, as `YYYY-MM-DD`.
 *
 * Stepped in UTC for the reason {@link nextDay} gives, and the two share this
 * so a window's far end and an agenda's tomorrow cannot be stepped two
 * different ways.
 */
function daysAfter(day: string, count: number): string {
  const stepped = new Date(`${day}T00:00:00Z`);
  stepped.setUTCDate(stepped.getUTCDate() + count);
  return stepped.toISOString().slice(0, 10);
}

/**
 * The mocked tomorrow, **fixed** rather than derived from the clock.
 *
 * `SUMMARY_ANCHOR` has to be the real today, because the page reads the
 * server's anchor; nothing requires the *mocked* tomorrow to track the
 * calendar, and deriving it made one assertion's strength depend on the day
 * the suite ran. A Wednesday in September is the longest label the row has to
 * hold, which is what the mobile-overflow test needs to be worth running.
 */
const MOCK_TOMORROW = '2026-09-30';

/**
 * The seven-day window both evidence sections are read for.
 *
 * **Derived from the anchor, not from `MOCK_TOMORROW`.** Those are different
 * days doing different jobs: the mocked tomorrow is the agenda disclosure's
 * label and is deliberately fixed, while this is a span the server computes
 * from the day it anchored on. Pairing `days_ahead: 7` with a fixed end date
 * a day after a *moving* start made a window that could not exist — the exact
 * defect these mocks were corrected to stop, reintroduced by copying the wrong
 * constant. Shared by both sections because the API sends them one window:
 * the tasks and the dates cover the same week by construction.
 */
const MOCK_WINDOW = {
  start_date: SUMMARY_ANCHOR,
  end_date: daysAfter(SUMMARY_ANCHOR, 7),
  days_ahead: 7,
};

/**
 * A ready upcoming-dates section holding nothing.
 *
 * `data: {}` served a payload the API cannot produce — the same mistake the
 * agenda's `tomorrow` note below records. Since ITER18-004 Phase 12 the card
 * reads this section, and a ready one that carries no `dates` is a broken
 * contract rather than an empty week, so these mocks now send the real shape.
 */
const MOCK_EMPTY_UPCOMING_DATES: HomeDashboardUpcomingDates = {
  window: MOCK_WINDOW,
  total: 0,
  dates: [],
};

/**
 * Nothing due this week, in the shape the endpoint really sends.
 *
 * Since ITER18-004 Phase 13 the tasks section carries a window and a total, so
 * a ready one holding `{}` is a broken contract rather than an empty week —
 * the same correction the dates mock above records. Nothing renders it until
 * Phase 14; the mock stops lying now.
 */
const MOCK_EMPTY_TASKS: HomeDashboardTasks = {
  window: MOCK_WINDOW,
  total: 0,
  tasks: [],
};

const REGENERATE_PATH = `**/api/journals/daily-summary/${SUMMARY_ANCHOR}/regenerate`;

const SUMMARY_PROSE = 'A quiet Wednesday. Two journals and one long walk.';
const REGENERATED_PROSE = 'A busier Wednesday after all. Three journals.';

/**
 * The wire values of the two enums the payload carries.
 *
 * The enums live in `src/lib/api/home-dashboard.ts`, which imports React Query
 * at module scope, so this spec takes them as **types only** and spells the
 * values itself. `satisfies` is what keeps that honest: a literal that drifted
 * from its enum fails `tsc`, where a bare `as` would accept any string at all.
 */
const READY =
  'ready' satisfies `${DashboardSectionStatus.READY}` as DashboardSectionStatus.READY;
const UNAVAILABLE =
  'unavailable' satisfies `${DashboardSectionStatus.UNAVAILABLE}` as DashboardSectionStatus.UNAVAILABLE;
const GENERATED =
  'generated' satisfies `${DashboardSummaryState.GENERATED}` as DashboardSummaryState.GENERATED;
const GENERATING =
  'generating' satisfies `${DashboardSummaryState.GENERATING}` as DashboardSummaryState.GENERATING;

type SummarySection = DashboardSection<HomeDashboardSummary>;

/** A section that answered, holding `data`. */
function ready<T>(data: T): DashboardSection<T> {
  return { status: READY, data };
}

const generatedSection = (summaryText: string): SummarySection =>
  ready<HomeDashboardSummary>({
    state: GENERATED,
    summary_text: summaryText,
    journal_count: 3,
    event_count: 2,
    contact_count: 4,
    mood_average: 7.5,
  });

const generatingSection: SummarySection = ready<HomeDashboardSummary>({
  state: GENERATING,
  summary_text: null,
  journal_count: 3,
  event_count: 2,
  contact_count: 4,
  mood_average: 7.5,
});

const unavailableSection: SummarySection = {
  status: UNAVAILABLE,
  data: null,
};

/** The sections a test serves; any it leaves out take the defaults below. */
type DashboardSections = Partial<HomeDashboardAttributes>;

/**
 * The dashboard document, **typed as the client reads it**.
 *
 * Every route mock in this file is built here. A route mock is a claim about
 * the wire contract that nothing else checks — ITER18-004 Phases 6 and 12 each
 * found one here serving a payload the API cannot produce — so building them
 * through `HomeDashboardResponse` is what puts `tsc` in front of that claim.
 *
 * A section a test does not name is the quiet default: the summary
 * unavailable, and the three evidence sections ready and empty.
 */
function dashboardDocument(
  sections: DashboardSections = {}
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'e2e-user',
      attributes: {
        summary: unavailableSection,
        // `tomorrow` rides on every ready agenda (Phase 6). Omitting it
        // served a payload the API cannot produce, and the tomorrow
        // disclosure beneath today's list is drawn from it.
        agenda: ready({
          entries: [],
          tomorrow: { date: MOCK_TOMORROW, entries: [] },
        }),
        tasks: ready(MOCK_EMPTY_TASKS),
        upcoming_dates: ready(MOCK_EMPTY_UPCOMING_DATES),
        ...sections,
      },
    },
    meta: { anchor: { date: SUMMARY_ANCHOR, timezone: SUMMARY_TIMEZONE } },
  };
}

/**
 * Serve the dashboard for the life of the test, counting each read served.
 *
 * `sectionsFor` is a function so a test that regenerates can move the served
 * state on. The count is how a show-more proves it revealed rows the page
 * already held: a test compares it before and after the click, rather than
 * against an absolute number the page's own refetches are free to change.
 */
async function mockDashboardSections(
  page: Page,
  sectionsFor: () => DashboardSections
): Promise<{ served: () => number }> {
  let served = 0;
  await page.route('**/api/home-dashboard', async route => {
    served += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(dashboardDocument(sectionsFor())),
    });
  });
  return { served: () => served };
}

/**
 * Serve one summary state for the life of the test.
 *
 * `summaryFor` is a function so a test that regenerates can move the served
 * state on; the tests that do not simply return the same section every time.
 */
async function mockDashboard(
  page: Page,
  summaryFor: () => SummarySection
): Promise<void> {
  await mockDashboardSections(page, () => ({ summary: summaryFor() }));
}

function summaryCard(page: Page) {
  return page.getByTestId('dashboard-summary-card');
}

test.describe('Home Dashboard — the AI daily summary card', () => {
  test.describe('Generated (W7, W10)', () => {
    test('shows the summary in full over its four key stats', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => generatedSection(SUMMARY_PROSE));
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = summaryCard(page);
      await expect(card).toBeVisible();
      await expect(page.getByTestId('dashboard-summary-text')).toHaveText(
        SUMMARY_PROSE
      );

      const stats = page.getByTestId('dashboard-summary-stats');
      await expect(stats).toBeVisible();
      for (const label of ['Journals', 'Events', 'Contacts', 'Avg Mood']) {
        await expect(stats.getByText(label, { exact: true })).toBeVisible();
      }
      await expect(stats.getByText('7.5/10')).toBeVisible();
    });

    test('offers no way to edit the summary', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => generatedSection(SUMMARY_PROSE));
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(page.getByTestId('dashboard-summary-text')).toBeVisible();
      await expect(summaryCard(page).locator('input, textarea')).toHaveCount(0);
    });
  });

  test.describe('Generating (W8)', () => {
    test('badges the header and replaces the body with one line', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => generatingSection);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(summaryCard(page).getByText('Generating...')).toBeVisible();
      await expect(
        page.getByText('Summary is being generated...')
      ).toBeVisible();
      await expect(page.getByTestId('dashboard-summary-text')).toHaveCount(0);
    });

    /**
     * The state this phase's central ruling rests on: nothing moves a summary
     * out of `pending`, so the card deliberately does **not** regenerate for
     * the reader — which only works if the control they would press is live.
     */
    test('keeps Regenerate offered and usable inside this state', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => generatingSection);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByText('Summary is being generated...')
      ).toBeVisible();
      await expect(
        page.getByRole('button', { name: /regenerate/i })
      ).toBeEnabled();
    });

    /**
     * The other half of the ruling, and the half an enabled-button assertion
     * cannot see: the card must not regenerate **for** the reader.
     *
     * A regression that fired the endpoint on seeing `generating` while leaving
     * the button enabled would satisfy every other test in this block. This one
     * watches the network instead — the count of regenerate requests must stay
     * at zero for as long as the card is simply sitting there in the state that
     * would tempt it.
     */
    test('never regenerates for itself while the summary reports generating', async ({
      authenticatedPage: page,
    }) => {
      const regenerateCalls: string[] = [];
      await mockDashboard(page, () => generatingSection);
      await page.route(REGENERATE_PATH, async route => {
        regenerateCalls.push(route.request().method());
        await route.fulfill({ status: 200, body: '{}' });
      });

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);
      await expect(
        page.getByText('Summary is being generated...')
      ).toBeVisible();

      // Give the card room to misbehave: an effect-driven POST would have
      // fired well inside this, and the dashboard query's own refetch on focus
      // is another chance for it.
      await page.waitForTimeout(2000);
      await page.getByRole('heading', { level: 1 }).click();
      await page.waitForTimeout(500);

      expect(regenerateCalls).toEqual([]);
    });

    test('draws no key-stats footer', async ({ authenticatedPage: page }) => {
      await mockDashboard(page, () => generatingSection);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByText('Summary is being generated...')
      ).toBeVisible();
      await expect(page.getByTestId('dashboard-summary-stats')).toHaveCount(0);
    });
  });

  test.describe('Unavailable (W9)', () => {
    test('says so in one quiet line and keeps Regenerate offered', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => unavailableSection);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByTestId('dashboard-summary-unavailable')
      ).toContainText(/everything below still works/i);
      await expect(
        page.getByRole('button', { name: /regenerate/i })
      ).toBeEnabled();
      await expect(page.getByTestId('dashboard-summary-stats')).toHaveCount(0);
    });

    test('leaves the three evidence sections rendering beside it', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => unavailableSection);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByTestId('dashboard-summary-unavailable')
      ).toBeVisible();

      const regions = sections(page);
      await expect(regions).toHaveCount(SECTION_NAMES.length);
      for (const [index, name] of SECTION_NAMES.entries()) {
        await expect(regions.nth(index)).toHaveAccessibleName(name);
      }
    });
  });

  test.describe('Regenerate (W6)', () => {
    test('re-reads the summary in place without leaving the page', async ({
      authenticatedPage: page,
    }) => {
      let served = generatedSection(SUMMARY_PROSE);
      const methodsSeen: string[] = [];
      await mockDashboard(page, () => served);
      await page.route(REGENERATE_PATH, async route => {
        methodsSeen.push(route.request().method());
        served = generatedSection(REGENERATED_PROSE);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: {
              type: 'journal-daily-summaries',
              id: SUMMARY_ANCHOR,
              attributes: {
                summary_date: SUMMARY_ANCHOR,
                summary_text: REGENERATED_PROSE,
                journal_count: 3,
                event_count: 2,
                contact_count: 4,
                mood_average: 7.5,
                status: 'generated',
              },
            },
          }),
        });
      });

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);
      await expect(page.getByTestId('dashboard-summary-text')).toHaveText(
        SUMMARY_PROSE
      );

      await Promise.all([
        // Matched on the verb as well as the path. The route above fulfils
        // this URL for every method, so a waiter that only matched the URL
        // would still pass if the mutation quietly became a GET — which is
        // the one thing about the endpoint contract this test claims to hold.
        page.waitForResponse(
          response =>
            response.url().includes('/regenerate') &&
            response.request().method() === 'POST'
        ),
        page.getByRole('button', { name: /regenerate/i }).click(),
      ]);

      // Exactly one write, and a POST: a second would mean the card fires for
      // itself somewhere, which the phase's central ruling forbids.
      expect(methodsSeen).toEqual(['POST']);
      await expect(page.getByTestId('dashboard-summary-text')).toHaveText(
        REGENERATED_PROSE
      );
      await expect(page).toHaveURL(/\/$/);
    });
  });

  test.describe('Layout (W5, W3)', () => {
    test('sits above the section grid and overflows nothing at mobile width', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboard(page, () => generatedSection(SUMMARY_PROSE));
      await page.setViewportSize(MOBILE);
      await openDashboard(page);

      const cardBox = await summaryCard(page).boundingBox();
      const gridBox = await page
        .getByTestId('dashboard-sections')
        .boundingBox();
      expect(cardBox).not.toBeNull();
      expect(gridBox).not.toBeNull();
      expect(cardBox!.y).toBeLessThan(gridBox!.y);

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    });
  });
});

/**
 * Home Dashboard — the agenda card (ITER18-004 Phase 7)
 *
 * **W11**–**W18** and wireframe gap 1: today's event journals as bordered
 * accent-bar rows, all-day above timed, each with its title link, time and
 * location, tags and participants; the cancelled marker; and the single line
 * for a day with nothing on it.
 *
 * Fixture-driven, unlike the summary block above: an event journal *can* be
 * created deterministically, so each test seeds its own through the API and
 * asserts only on rows it created, by the unique titles the data manager
 * gave them. Other specs in the run may leave journals on the same day; every
 * assertion here is scoped to this test's own rows, and the ordering tests
 * compare those rows' positions rather than counting the list.
 *
 * **The e2e user has no configured timezone**, so the backend's day
 * boundaries are UTC. Every journal is therefore placed at **noon UTC today**
 * with `timezone: 'UTC'` on its event data — a local-noon instant can read as
 * tomorrow (or yesterday) on a UTC-anchored dashboard, which is the Phase 17
 * fixture rule.
 *
 * The one mocked test is the empty state, for the reason the summary block
 * gives for `unavailable`: the account is shared across the run, so a
 * real-data "nothing scheduled" would depend on suite ordering.
 */

const AGENDA_LIST_NAME = "Today's agenda";
const AGENDA_EMPTY_LINE = 'Nothing scheduled today.';

/**
 * The day the dashboard is anchored on, read from the API — once per test.
 *
 * The e2e user has no configured timezone, so this is the UTC day, and every
 * fixture in a test is placed on it rather than on a `new Date()` read at
 * seeding time: a date read per fixture can straddle 00:00 UTC and split one
 * test's events across two days. Reading the anchor also documents where
 * "today" comes from — the server, as the page-shell test above insists.
 *
 * **The page reads the anchor again for itself**, so UTC midnight can pass
 * between this read and the one the page renders. A test whose *expectation*
 * depends on the day must therefore not take it from here: the tasks and
 * upcoming-dates conformance tests assert labels that read the same on either
 * side of midnight, or compute them from `captureServedAnchor`. The agenda tests
 * that seed events on *today* keep a residual window — an event seeded for
 * today is yesterday's after midnight, and no expectation can follow that
 * without a server clock the suite controls.
 */
async function anchorDay(page: Page): Promise<string> {
  const response = await page.request.get('/api/home-dashboard');
  expect(response.ok()).toBe(true);
  return (await response.json()).meta.anchor.date as string;
}

/**
 * A clock time on the anchor day, as a UTC ISO instant.
 *
 * A timed event's `event_date_range` carries the instant it begins, and that
 * instant — not the clock column — is what the agenda orders timed entries
 * by (wireframe gap 12). So a fixture's instant must agree with its clock
 * time, or two events seeded at the same instant would tie and fall back to
 * creation order. `12:00:00` is used for all-day events, which match by date.
 */
function atUtc(day: string, clock: string): string {
  return new Date(`${day}T${clock}Z`).toISOString();
}

interface AgendaEventFixture {
  title: string;
  allDay?: boolean;
  startTime?: string;
  endTime?: string;
  location?: string;
  calendarId: string;
  contactIds?: string[];
}

/** One event journal on the anchor day's agenda, created through the API. */
async function createAgendaEvent(
  dataManager: TestDataManager,
  day: string,
  fixture: AgendaEventFixture
): Promise<TestJournal> {
  const timed = !fixture.allDay;
  const start = atUtc(
    day,
    timed && fixture.startTime ? fixture.startTime : '12:00:00'
  );
  const end = atUtc(
    day,
    timed && fixture.endTime ? fixture.endTime : '12:00:00'
  );
  return dataManager.createJournal({
    title: fixture.title,
    content: 'Seeded for the agenda card e2e.',
    event_date_range: { start, end },
    types: ['event'],
    type_data: {
      event: {
        calendar_id: fixture.calendarId,
        is_all_day: !timed,
        sync_invitees: false,
        timezone: 'UTC',
        ...(timed && fixture.startTime
          ? { start_time: fixture.startTime }
          : {}),
        ...(timed && fixture.endTime ? { end_time: fixture.endTime } : {}),
        ...(fixture.location ? { location: fixture.location } : {}),
      },
    },
    ...(fixture.contactIds
      ? {
          contacts: fixture.contactIds.map(contactId => ({
            contact_id: contactId,
            relationship_type: 'PARTICIPANT',
          })),
        }
      : {}),
  });
}

function agendaList(page: Page) {
  return page.getByRole('list', { name: AGENDA_LIST_NAME });
}

/**
 * A locator's bounding box, asserted present rather than asserted away.
 *
 * The same guard `sectionBoxes` uses: a null box should fail as an assertion
 * naming the element, not as a `TypeError` on a property read.
 */
async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

/**
 * A day as `Wednesday, 30 September` — the weekday-and-date half of the
 * disclosure's label (**W19**), and an upcoming date's occurrence (**W31**,
 * wireframe gap 20, which settled that both carry the comma).
 *
 * Built with `Intl` in UTC — deliberately not the app's `formatIsoWeekdayDate`
 * — so this asserts what the row should say rather than re-running the code
 * that says it.
 */
function expectedWeekdayDate(day: string): string {
  const at = new Date(`${day}T00:00:00Z`);
  const weekday = new Intl.DateTimeFormat('en-AU', {
    timeZone: 'UTC',
    weekday: 'long',
  }).format(at);
  const dayMonth = new Intl.DateTimeFormat('en-AU', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'long',
  }).format(at);
  // W19 writes the comma; `Intl` does not put one in on its own.
  return `${weekday}, ${dayMonth}`;
}

/** The agenda row for one seeded journal, by the id the row carries. */
function agendaRow(page: Page, journal: TestJournal) {
  return agendaList(page).getByTestId(`agenda-entry-${journal.id}`);
}

/** One mocked agenda entry, in the payload's shape. */
function mockEntry(
  journalId: number,
  title: string,
  startTime: string
): HomeDashboardAgendaEntry {
  return {
    journal_id: journalId,
    title,
    is_all_day: false,
    starts_at: `${MOCK_TOMORROW}T${startTime}Z`,
    ends_at: `${MOCK_TOMORROW}T${startTime}Z`,
    start_time: startTime,
    end_time: null,
    timezone: 'UTC',
    location: null,
    calendar_color: '#8B5CF6',
    is_cancelled: false,
    tags: [],
    participants: [],
  };
}

/**
 * Serve a dashboard whose agenda is ready, with the given days.
 *
 * The counts and the empty states are asserted against a mock for the reason
 * the summary block gives for `unavailable`: the account is shared across the
 * run, so an exact count read from real data would depend on suite ordering.
 * The behavioural tests below use real fixtures and assert only their own rows.
 */
async function mockAgenda(
  page: Page,
  agenda: {
    entries?: HomeDashboardAgendaEntry[];
    tomorrow?: HomeDashboardAgendaEntry[];
  } = {}
): Promise<void> {
  await mockDashboardSections(page, () => ({
    agenda: ready({
      entries: agenda.entries ?? [],
      tomorrow: { date: MOCK_TOMORROW, entries: agenda.tomorrow ?? [] },
    }),
  }));
}

/** Serve a dashboard whose agenda is ready and empty, today and tomorrow. */
async function mockEmptyAgenda(page: Page): Promise<void> {
  await mockAgenda(page);
}

test.describe('Home Dashboard — the agenda card', () => {
  test.describe('Ordering and entry elements (W12, W13, W14, W17)', () => {
    test('lists the all-day entry above timed entries in time order, each with its details', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Card Cal', color: '#8B5CF6' },
      ]);
      // Seeded deliberately out of order: the card must not simply draw them
      // in creation order.
      const dinner = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Dinner',
        startTime: '19:00:00',
        endTime: '21:00:00',
        calendarId: calendar.id,
      });
      const standup = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Standup',
        startTime: '09:00:00',
        endTime: '09:30:00',
        location: 'The small room',
        calendarId: calendar.id,
      });
      const holiday = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Holiday',
        allDay: true,
        calendarId: calendar.id,
      });

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const holidayRow = agendaRow(page, holiday);
      const standupRow = agendaRow(page, standup);
      const dinnerRow = agendaRow(page, dinner);
      await expect(holidayRow).toBeVisible();
      await expect(standupRow).toBeVisible();
      await expect(dinnerRow).toBeVisible();

      // W12 then W13: all-day first, then ascending by start.
      const [holidayBox, standupBox, dinnerBox] = await Promise.all([
        holidayRow.boundingBox(),
        standupRow.boundingBox(),
        dinnerRow.boundingBox(),
      ]);
      expect(holidayBox!.y).toBeLessThan(standupBox!.y);
      expect(standupBox!.y).toBeLessThan(dinnerBox!.y);

      // W12: the marker in place of a time.
      await expect(holidayRow.getByTestId('agenda-entry-all-day')).toHaveText(
        /all day/i
      );
      await expect(holidayRow.getByTestId('agenda-entry-time')).toHaveCount(0);

      // W13: the clock range and the location beside it.
      await expect(standupRow.getByTestId('agenda-entry-time')).toHaveText(
        '09:00 – 09:30'
      );
      await expect(standupRow.getByTestId('agenda-entry-location')).toHaveText(
        'The small room'
      );
      await expect(dinnerRow.getByTestId('agenda-entry-time')).toHaveText(
        '19:00 – 21:00'
      );
      await expect(dinnerRow.getByTestId('agenda-entry-location')).toHaveCount(
        0
      );

      // W17: the accent bar keyed to the calendar's colour.
      await expect(standupRow.getByTestId('agenda-entry-accent')).toHaveCSS(
        'background-color',
        'rgb(139, 92, 246)'
      );
    });

    test('links each title to its journal', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Link Cal', color: '#10B981' },
      ]);
      const standup = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Linked Standup',
        startTime: '09:00:00',
        endTime: '09:30:00',
        calendarId: calendar.id,
      });

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const link = agendaRow(page, standup).getByRole('link', {
        name: standup.title,
      });
      await expect(link).toBeVisible();
      await link.click();

      await expect(page).toHaveURL(new RegExp(`/journals/${standup.id}$`));
    });
  });

  test.describe('Tags and participants (W15, W16)', () => {
    test('shows the tag in its colour and every participant by name', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Tag Cal', color: '#3B82F6' },
      ]);
      const [tag] = await dataManager.createJournalTags([
        { name: 'agenda-social', color: '#EF4444' },
      ]);
      const [sam, alex] = await dataManager.createContacts([
        { firstName: 'Sam', lastName: 'Taylor' },
        { firstName: 'Alex', lastName: 'Chen' },
      ]);
      const coffee = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Coffee',
        startTime: '10:00:00',
        endTime: '10:30:00',
        calendarId: calendar.id,
        contactIds: [sam.id, alex.id],
      });
      await dataManager.assignTagsToJournal(coffee.id, [tag.id]);

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const row = agendaRow(page, coffee);
      await expect(row).toBeVisible();

      const badge = row.getByTestId('agenda-entry-tags').getByText(tag.name);
      await expect(badge).toBeVisible();
      await expect(badge).toHaveCSS('border-color', 'rgb(239, 68, 68)');

      const participants = row.getByRole('list', { name: 'Participants' });
      await expect(
        participants.getByRole('img', {
          name: `${sam.firstName} ${sam.lastName}`,
        })
      ).toBeVisible();
      await expect(
        participants.getByRole('img', {
          name: `${alex.firstName} ${alex.lastName}`,
        })
      ).toBeVisible();
    });
  });

  test.describe('Cancelled entries (W18)', () => {
    test('shows a cancelled event marked, beside a confirmed one that is not', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Cancel Cal', color: '#F59E0B' },
      ]);
      const cancelled = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Cancelled Lunch',
        startTime: '12:00:00',
        endTime: '13:00:00',
        calendarId: calendar.id,
      });
      const confirmed = await createAgendaEvent(dataManager, day, {
        title: 'Agenda Confirmed Walk',
        startTime: '17:00:00',
        endTime: '18:00:00',
        calendarId: calendar.id,
      });
      // Asserted, not assumed: if cancelling ever stopped succeeding the test
      // below would otherwise pass against two confirmed rows.
      const response = await dataManager.cancelJournal(cancelled.id);
      expect(response.ok()).toBe(true);

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const cancelledRow = agendaRow(page, cancelled);
      const confirmedRow = agendaRow(page, confirmed);
      await expect(cancelledRow).toBeVisible();
      await expect(confirmedRow).toBeVisible();

      await expect(
        cancelledRow.getByTestId('agenda-entry-cancelled')
      ).toHaveText(/cancelled/i);
      await expect(
        cancelledRow.getByRole('link', { name: cancelled.title })
      ).toHaveCSS('text-decoration-line', 'line-through');
      await expect(
        confirmedRow.getByTestId('agenda-entry-cancelled')
      ).toHaveCount(0);
    });
  });

  test.describe('Nothing scheduled (gap 1, W29 idiom)', () => {
    test('says so in a single line with no rows', async ({
      authenticatedPage: page,
    }) => {
      await mockEmptyAgenda(page);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('agenda-card');
      await expect(card.getByText(AGENDA_EMPTY_LINE)).toBeVisible();
      await expect(agendaList(page).getByRole('listitem')).toHaveCount(0);
      await expect(card.getByRole('alert')).toHaveCount(0);
    });
  });

  /**
   * The tomorrow disclosure (**W19**, **W20**).
   *
   * Clicks are gated on the trigger's `aria-expanded` rather than on the
   * panel's visibility: the panel slides, and asking whether it is visible
   * races that animation (the recorded Radix one-shot race). `aria-expanded`
   * is the state, not a rendering of it.
   */
  test.describe('Tomorrow (W19, W20)', () => {
    test('opens tomorrow’s entries in place beneath today, then shuts again', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const today = await anchorDay(page);
      const tomorrow = nextDay(today);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Tomorrow Cal', color: '#0EA5E9' },
      ]);
      const todayStandup = await createAgendaEvent(dataManager, today, {
        title: 'Agenda Today Standup',
        startTime: '09:00:00',
        endTime: '09:30:00',
        calendarId: calendar.id,
      });
      const tomorrowHoliday = await createAgendaEvent(dataManager, tomorrow, {
        title: 'Agenda Tomorrow Holiday',
        allDay: true,
        calendarId: calendar.id,
      });
      const tomorrowRetro = await createAgendaEvent(dataManager, tomorrow, {
        title: 'Agenda Tomorrow Retro',
        startTime: '16:00:00',
        endTime: '17:00:00',
        location: 'The big room',
        calendarId: calendar.id,
      });

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('agenda-card');
      const trigger = card.getByTestId('tomorrow-trigger');
      const holidayRow = card.getByTestId(`agenda-entry-${tomorrowHoliday.id}`);
      const retroRow = card.getByTestId(`agenda-entry-${tomorrowRetro.id}`);
      const todayRow = agendaRow(page, todayStandup);

      // Collapsed on arrival: today is drawn, tomorrow is not (W19).
      await expect(todayRow).toBeVisible();
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      // The whole label, against the day the API itself resolved — the prefix
      // alone would pass on a row drawn a day out. Formatted here with `Intl`
      // rather than the app's own `date-fns` helper, so the assertion is
      // independent of the code it is checking.
      await expect(page.getByTestId('tomorrow-label')).toHaveText(
        `Tomorrow — ${expectedWeekdayDate(tomorrow)}`
      );
      await expect(holidayRow).toHaveCount(0);
      await expect(retroRow).toHaveCount(0);
      const urlBefore = page.url();

      await trigger.click();
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');

      // W20: tomorrow's entries in the W12–W18 form, all-day above timed.
      await expect(holidayRow.getByTestId('agenda-entry-all-day')).toHaveText(
        /all day/i
      );
      await expect(retroRow.getByTestId('agenda-entry-time')).toHaveText(
        '16:00 – 17:00'
      );
      await expect(retroRow.getByTestId('agenda-entry-location')).toHaveText(
        'The big room'
      );
      const holidayBox = await boxOf(holidayRow);
      const retroBox = await boxOf(retroRow);
      expect(holidayBox.y).toBeLessThan(retroBox.y);

      // In place: today is still on screen and nothing navigated.
      await expect(todayRow).toBeVisible();
      expect(page.url()).toBe(urlBefore);
      // The expanded panel is the only region the card adds, and it opens
      // beneath today's list rather than replacing it.
      const todayBox = await boxOf(todayRow);
      expect(todayBox.y).toBeLessThan(holidayBox.y);

      await trigger.click();
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      await expect(holidayRow).toHaveCount(0);
    });

    test('counts what is behind it before it is opened', async ({
      authenticatedPage: page,
    }) => {
      await mockAgenda(page, {
        tomorrow: [
          mockEntry(9001, 'Mocked tomorrow standup', '09:00:00'),
          mockEntry(9002, 'Mocked tomorrow retro', '16:00:00'),
        ],
      });
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('agenda-card');
      await expect(card.getByTestId('tomorrow-count')).toHaveText('2 events');
      await expect(card.getByTestId('tomorrow-trigger')).toHaveAttribute(
        'aria-expanded',
        'false'
      );
    });

    test('keeps its row on a clear tomorrow, counting none', async ({
      authenticatedPage: page,
    }) => {
      await mockEmptyAgenda(page);
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('agenda-card');
      const trigger = card.getByTestId('tomorrow-trigger');
      await expect(trigger).toBeVisible();
      await expect(card.getByTestId('tomorrow-count')).toHaveText('0 events');

      await trigger.click();
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');

      await expect(card.getByText('Nothing scheduled tomorrow.')).toBeVisible();
      await expect(
        page.getByRole('list', { name: "Tomorrow's agenda" })
      ).toHaveCount(0);
      await expect(card.getByRole('alert')).toHaveCount(0);
    });

    test('reaches tomorrow at mobile width without overflowing', async ({
      authenticatedPage: page,
    }) => {
      await mockAgenda(page, {
        tomorrow: [mockEntry(9003, 'Mocked tomorrow standup', '09:00:00')],
      });
      await page.setViewportSize(MOBILE);
      await openDashboard(page);

      const trigger = page
        .getByTestId('agenda-card')
        .getByTestId('tomorrow-trigger');
      await trigger.click();
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByTestId('agenda-entry-9003')).toBeVisible();

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    });
  });

  test.describe('Layout (W3)', () => {
    test('overflows nothing at mobile width with a long title, many tags and many participants', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      const [calendar] = await dataManager.createCalendars([
        { name: 'Agenda Mobile Cal', color: '#EC4899' },
      ]);
      const tags = await dataManager.createJournalTags([
        { name: 'agenda-mobile-one' },
        { name: 'agenda-mobile-two' },
        { name: 'agenda-mobile-three' },
        { name: 'agenda-mobile-four' },
      ]);
      const contacts = await dataManager.createContacts([
        { firstName: 'Priya', lastName: 'Patel' },
        { firstName: 'Jordan', lastName: 'Lee' },
        { firstName: 'Kim', lastName: 'Nguyen' },
        { firstName: 'Taylor', lastName: 'Brooks' },
      ]);
      const busy = await createAgendaEvent(dataManager, day, {
        title:
          'Agenda Quarterly planning offsite with the whole extended leadership group',
        startTime: '09:00:00',
        endTime: '17:00:00',
        location: 'The Grand Conference Centre, Level 12, Boardroom B',
        calendarId: calendar.id,
        contactIds: contacts.map(contact => contact.id),
      });
      await dataManager.assignTagsToJournal(
        busy.id,
        tags.map(tag => tag.id)
      );

      await page.setViewportSize(MOBILE);
      await openDashboard(page);

      const row = agendaRow(page, busy);
      await expect(row).toBeVisible();
      // Four participants: three drawn, one folded into the counter (W16).
      await expect(row.getByText('+1', { exact: true })).toBeVisible();

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    });
  });
});

/**
 * The tasks card's one behaviour that only a real stack can prove
 * (ITER18-004 Phase 14, **W24**).
 *
 * Everything else about this card — the five-row cap, each chip case, the
 * order, the empty and unavailable states — is asserted in RTL against the
 * payload, and Phase 17 owns the structural wireframe sweep. What is left for
 * this level is the round trip: a real task, ticked through the real endpoint,
 * leaving the section **without navigating** and **without the summary
 * changing**. That is Phase 17's own second criterion, discharged here because
 * the *Phase Completion Requirements* allow deferring e2e only for a phase
 * with no user-visible surface, and this phase is the surface.
 *
 * Fixtures are anchored on the day the **server** says it is and stepped in
 * UTC, because the e2e user has no configured timezone: a journal seeded at
 * local noon can land on tomorrow's dashboard, which is the Phase 17 fixture
 * rule.
 */

const TASKS_LIST_NAME = 'Tasks due in the next seven days';

/** The tasks card's list, by the accessible name the card gives it (W4). */
function tasksList(page: Page) {
  return page.getByRole('list', { name: TASKS_LIST_NAME });
}

/**
 * A task due `dueInDays` out (two by default), with both its anchors, on the
 * anchor day.
 *
 * Never the window's last day: that is its edge, and a UTC midnight passing
 * between seeding and the page's own read would push a task seeded there out
 * of the window and fail the test for a reason that has nothing to do with the
 * card.
 */
async function createDashboardTask(
  dataManager: TestDataManager,
  day: string,
  text: string,
  dueInDays = 2
): Promise<{ task: TestTask; dueJournal: TestJournal }> {
  const dueDay = daysAfter(day, dueInDays);

  const creating = await dataManager.createJournal({
    title: 'Tasks card journal it came from',
    content: 'Task anchor seeded for the dashboard tasks card',
    event_date_range: {
      start: atUtc(day, '09:00:00'),
      end: atUtc(day, '10:00:00'),
    },
  });
  const dueJournal = await dataManager.createJournal({
    title: 'Tasks card journal it is due in',
    content: 'Task anchor seeded for the dashboard tasks card',
    event_date_range: {
      start: atUtc(dueDay, '09:00:00'),
      end: atUtc(dueDay, '10:00:00'),
    },
  });

  const task = await dataManager.createTask({
    creatingJournalId: creating.id,
    dueJournalId: dueJournal.id,
    text,
  });

  return { task, dueJournal };
}

/**
 * The `PATCH` the done button sends, awaited rather than inferred.
 *
 * A mutation, so it is safe to wait on: the observer trap that makes
 * `waitForResponse` unreliable for *queries* — a mounted observer silencing the
 * refetch — does not apply to a write the button issues directly.
 */
function writeFor(page: Page, task: TestTask) {
  return page.waitForResponse(
    response =>
      response.url().includes(`/api/tasks/${task.id}`) &&
      response.request().method() === 'PATCH'
  );
}

/** Every task row the list draws — and none of the contacts nested in them. */
function taskRows(page: Page) {
  return tasksList(page).locator(':scope > li');
}

/**
 * One mocked task `daysAway` into the window, in the payload's shape.
 *
 * Each is due in a journal of its own, and each names a contact, so every row
 * holds a nested list item of its own: a row count that counted those would
 * read double and fail, which is what makes `taskRows` provably row-scoped.
 */
function mockTask(taskId: number, daysAway: number): HomeDashboardTask {
  return {
    task_id: taskId,
    text: `Mocked task ${taskId}`,
    due_journal: {
      id: taskId + 1000,
      title: `Mocked due journal ${taskId}`,
      date: daysAfter(SUMMARY_ANCHOR, daysAway),
    },
    days_away: daysAway,
    contacts: [
      { contact_id: taskId + 2000, name: 'Mocked Contact', photo_url: null },
    ],
  };
}

/**
 * **W25**'s absolute short form — `Thu 17 Sep` — for a due day past tomorrow.
 *
 * Built from `Intl` parts in UTC rather than with the app's date-fns helper,
 * so this asserts what the chip should say rather than re-running the code
 * that says it. The parts come from `en-US` and the order is assembled here:
 * CLDR's Australian short month for September is `Sept`, where the app and
 * **W25** both write three letters.
 */
function expectedShortDueLabel(day: string): string {
  const at = new Date(`${day}T00:00:00Z`);
  const part = (options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', ...options }).format(
      at
    );
  return `${part({ weekday: 'short' })} ${Number(day.slice(8, 10))} ${part({ month: 'short' })}`;
}

test.describe('Home Dashboard — the tasks card', () => {
  test('ticks a task off in place, without leaving the page (W24)', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);

    const { task, dueJournal } = await createDashboardTask(
      dataManager,
      day,
      'Tasks card send the deposit receipt'
    );

    await openDashboard(page);

    const row = tasksList(page).getByTestId(`dashboard-task-${task.id}`);
    await expect(row).toBeVisible();
    await expect(
      row.getByText('Tasks card send the deposit receipt')
    ).toBeVisible();
    // W26: the row names the journal it is due in, and links to it.
    await expect(
      row.getByRole('link', { name: dueJournal.title })
    ).toHaveAttribute('href', `/journals/${dueJournal.id}`);

    const urlBefore = page.url();

    // AC6: the summary is not regenerated underneath the user — it refreshes
    // on the next load, which is the contract ITER18-005 Phase 7 relies on.
    // Asserted against the *requests* rather than against the card's text:
    // nothing here establishes a summary before the tick, so comparing its words
    // would pass however the page behaved. The *generated end to end* block
    // establishes one and asserts the words as well.
    const summaryRequests: string[] = [];
    page.on('request', request => {
      if (request.url().includes('daily-summary')) {
        summaryRequests.push(request.url());
      }
    });

    const write = writeFor(page, task);
    await row.getByRole('button', { name: 'Mark done' }).click();

    // The section updates in place: the row goes, and the page does not.
    await expect(row).toHaveCount(0);
    expect(page.url()).toBe(urlBefore);
    // `toBeAttached`, not `toBeVisible`: the card keeps its labelled list in
    // the DOM whether or not it holds entries (**W4**) — a `display:none` list
    // is out of the accessibility tree — and an empty `<ul>` has no box, so
    // "visible" is the wrong question to ask of it.
    await expect(tasksList(page)).toBeAttached();
    await expect(summaryCard(page)).toBeVisible();

    // Only now: the row went optimistically, so the write is still in flight
    // and a request assertion made here would be about the wrong moment.
    await write;
    expect(summaryRequests).toEqual([]);
  });

  test('leaves the task on its journal, where it is worked with', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);

    const { task, dueJournal } = await createDashboardTask(
      dataManager,
      day,
      'Tasks card confirm the caterer'
    );

    await openDashboard(page);

    const row = tasksList(page).getByTestId(`dashboard-task-${task.id}`);
    await expect(row).toBeVisible();

    // **Waited on before the read below, and the row leaving is not a
    // substitute for it.** The removal is optimistic, so the row is gone the
    // instant the button is pressed and the DOM says nothing about whether the
    // server has answered — asserting the record straight after `toHaveCount`
    // read `not_done` on Mobile Chrome and passed on Firefox by timing alone.
    const write = writeFor(page, task);
    await row.getByRole('button', { name: 'Mark done' }).click();
    await expect(row).toHaveCount(0);
    await write;

    // Hidden from the dashboard, not lost: the specification's stance on
    // everything this section drops. Read back through the API rather than a
    // second page, because what is being asserted is the record, not a second
    // surface's rendering of it.
    const response = await page.request.get(
      `/api/journals/${dueJournal.id}/tasks`
    );
    expect(response.ok()).toBe(true);
    const body = await response.json();
    const stored = body.data.find(
      (resource: { id: string }) => resource.id === task.id
    );
    expect(stored.attributes.status).toBe('done');
    expect(stored.attributes.text).toBe('Tasks card confirm the caterer');
  });

  /**
   * The structural sweep ITER18-004 Phase 17 owns (**W22**, **W25**, **W28**,
   * **W29**).
   *
   * The cap and the empty state are served, for the reason the agenda block
   * gives for its counts: the account is shared across the run, so a count
   * read from real data would depend on suite ordering. The order is seeded,
   * and asserted only between this test's own rows.
   */
  test.describe('Wireframe conformance', () => {
    test('draws five rows and names the whole week, then reveals the rest in place (W22, W28)', async ({
      authenticatedPage: page,
    }) => {
      const week = Array.from({ length: 7 }, (_, index) =>
        mockTask(9101 + index, index + 1)
      );
      const dashboard = await mockDashboardSections(page, () => ({
        tasks: ready({ window: MOCK_WINDOW, total: week.length, tasks: week }),
      }));
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('tasks-card');
      await expect(taskRows(page)).toHaveCount(5);
      await expect(tasksList(page).getByText('Mocked task 9106')).toHaveCount(
        0
      );
      const showMore = card.getByRole('button', {
        name: 'Show all 7 due this week',
      });
      await expect(showMore).toBeVisible();

      const urlBefore = page.url();
      const readsBefore = dashboard.served();
      await showMore.click();

      // In place: the remainder is drawn from the payload already held, the
      // control withdraws, and nothing navigated or re-read the dashboard.
      await expect(taskRows(page)).toHaveCount(7);
      await expect(tasksList(page).getByText('Mocked task 9107')).toBeVisible();
      await expect(showMore).toHaveCount(0);
      expect(page.url()).toBe(urlBefore);
      expect(dashboard.served()).toBe(readsBefore);
    });

    test('orders its own tasks soonest first, each with its due chip (W22, W25)', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);
      testCleanup(() => dataManager.cleanup());
      const day = await anchorDay(page);

      // Seeded latest first, so creation order cannot pass for the rule. Three
      // and five days out, so both chips take W25's absolute short form and
      // keep it if UTC midnight passes before the page reads its own anchor:
      // a task seeded for tomorrow would then correctly read `Today`. The
      // relative labels are pinned in `dashboard-tasks-display.test.ts` and
      // `DashboardTaskRow.test.tsx`, where the day is not a race.
      const later = await createDashboardTask(
        dataManager,
        day,
        'Tasks card book the venue',
        5
      );
      const sooner = await createDashboardTask(
        dataManager,
        day,
        'Tasks card post the invitations',
        3
      );

      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const soonerRow = tasksList(page).getByTestId(
        `dashboard-task-${sooner.task.id}`
      );
      const laterRow = tasksList(page).getByTestId(
        `dashboard-task-${later.task.id}`
      );
      await expect(soonerRow).toBeVisible();
      await expect(laterRow).toBeVisible();
      expect((await boxOf(soonerRow)).y).toBeLessThan(
        (await boxOf(laterRow)).y
      );

      // W25: the absolute short form, named by the due journal's own date.
      await expect(soonerRow.getByTestId('dashboard-task-chip')).toHaveText(
        expectedShortDueLabel(daysAfter(day, 3))
      );
      await expect(laterRow.getByTestId('dashboard-task-chip')).toHaveText(
        expectedShortDueLabel(daysAfter(day, 5))
      );
      // W26: each row names the journal it is due in, and links to it.
      await expect(
        laterRow.getByRole('link', { name: later.dueJournal.title })
      ).toHaveAttribute('href', `/journals/${later.dueJournal.id}`);
    });

    test('says in one line that nothing is due, as a good outcome (W29)', async ({
      authenticatedPage: page,
    }) => {
      await mockDashboardSections(page, () => ({}));
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      const card = page.getByTestId('tasks-card');
      await expect(
        card.getByText('Nothing due in the next seven days.')
      ).toBeVisible();
      // The labelled list stays in place (W4); it is simply empty.
      await expect(tasksList(page)).toBeAttached();
      await expect(taskRows(page)).toHaveCount(0);
      await expect(card.getByTestId('tasks-show-more')).toHaveCount(0);
      await expect(card.getByRole('alert')).toHaveCount(0);
    });
  });
});

/**
 * Home Dashboard — the upcoming dates card (ITER18-004 Phase 17, **W30**–
 * **W32**, wireframe gaps 2 and 3).
 *
 * The order and each row's elements are seeded — two contacts whose birthdays
 * fall inside the window — and asserted only between this test's own rows,
 * found by the link to each contact rather than by position. The cap and the
 * empty state are served, for the reason the agenda block gives for its
 * counts.
 *
 * **The e2e user has no configured timezone**, so the window is the UTC week
 * starting on the anchor the server reports, and each birthday's month and day
 * are taken from that anchor stepped in UTC. They sit three and five days out:
 * clear of the window's last day for the reason `createDashboardTask` gives,
 * and still "in N days" rather than "Tomorrow" if midnight passes before the
 * page reads — when N itself moves, which is why the chips are checked against
 * the anchor the page was served rather than the one the fixtures were seeded
 * from.
 */

const UPCOMING_LIST_NAME = 'Upcoming contact dates';

/** The wire value of a birthday, checked against its enum as `READY` is. */
const BIRTHDAY =
  'birthday' satisfies `${ImportantDateTypeEnum.BIRTHDAY}` as ImportantDateTypeEnum.BIRTHDAY;

function upcomingList(page: Page) {
  return page.getByRole('list', { name: UPCOMING_LIST_NAME });
}

function upcomingRows(page: Page) {
  return upcomingList(page).getByTestId('upcoming-date');
}

/** The row for one seeded contact, by the link to them (W31). */
function upcomingRowFor(page: Page, contact: TestContact) {
  return upcomingRows(page).filter({
    has: page.getByRole('link', {
      name: `${contact.firstName} ${contact.lastName}`,
    }),
  });
}

/** One mocked occurrence `daysAway` into the window, in the payload's shape. */
function mockUpcomingDate(
  contactId: number,
  daysAway: number
): HomeDashboardUpcomingDate {
  return {
    contact_id: contactId,
    contact_name: `Mocked Contact ${contactId}`,
    photo_url: null,
    date_type: BIRTHDAY,
    custom_date_type_name: null,
    occurs_on: daysAfter(SUMMARY_ANCHOR, daysAway),
    days_away: daysAway,
    years: null,
    observed_for_leap_day: false,
  };
}

/** The month and day of a `YYYY-MM-DD`, as an important date stores them. */
function monthAndDay(day: string): { month: number; day: number } {
  return { month: Number(day.slice(5, 7)), day: Number(day.slice(8, 10)) };
}

/** Whole calendar days from `from` to `to`, both `YYYY-MM-DD`. */
function daysBetween(from: string, to: string): number {
  const dayMs = 24 * 60 * 60 * 1000;
  return Math.round(
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / dayMs
  );
}

/**
 * The anchor day the page was actually **served**, for an expectation that
 * counts from it.
 *
 * `anchorDay` is read before seeding and the page reads again for itself, so
 * midnight can fall between the two; a chip counted from the seeding anchor
 * would then expect `in 3 days` of a dashboard correctly saying `in 2 days`.
 * The route passes the real response through untouched and only notes the
 * anchor it carried. `page.request` bypasses page routes, so `anchorDay`'s own
 * read is not among them. Install before navigating; read after the page has
 * settled, when the last anchor served is the one on screen.
 */
async function captureServedAnchor(page: Page): Promise<() => string> {
  const served: string[] = [];
  await page.route('**/api/home-dashboard', async route => {
    const response = await route.fetch();
    const body = (await response.json()) as HomeDashboardResponse;
    served.push(body.meta.anchor.date);
    await route.fulfill({ response, json: body });
  });
  return () => {
    expect(served.length).toBeGreaterThan(0);
    return served[served.length - 1];
  };
}

test.describe('Home Dashboard — the upcoming dates card', () => {
  test('orders its own dates soonest first, each with its in-N-days chip (W31)', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const anchor = await anchorDay(page);
    const laterDay = daysAfter(anchor, 5);
    const soonerDay = daysAfter(anchor, 3);
    const servedAnchor = await captureServedAnchor(page);

    // Seeded latest first, so creation order cannot pass for the rule. The
    // later one has a year, so it carries an age; the sooner one does not, so
    // its badge degrades to the bare type (W31).
    const [later] = await dataManager.createContacts([
      {
        firstName: 'Upcoming',
        lastName: 'Later',
        importantDates: [
          {
            date_type: BIRTHDAY,
            precision: 'full',
            year: 1990,
            ...monthAndDay(laterDay),
          },
        ],
      },
    ]);
    const [sooner] = await dataManager.createContacts([
      {
        firstName: 'Upcoming',
        lastName: 'Sooner',
        importantDates: [
          {
            date_type: BIRTHDAY,
            precision: 'day_month',
            ...monthAndDay(soonerDay),
          },
        ],
      },
    ]);

    await page.setViewportSize(DESKTOP);
    await openDashboard(page);

    const soonerRow = upcomingRowFor(page, sooner);
    const laterRow = upcomingRowFor(page, later);
    await expect(soonerRow).toBeVisible();
    await expect(laterRow).toBeVisible();
    expect((await boxOf(soonerRow)).y).toBeLessThan((await boxOf(laterRow)).y);

    // Counted from the anchor the page rendered, not the one seeded from.
    await expect(soonerRow.getByTestId('upcoming-date-chip')).toHaveText(
      `in ${daysBetween(servedAnchor(), soonerDay)} days`
    );
    await expect(laterRow.getByTestId('upcoming-date-chip')).toHaveText(
      `in ${daysBetween(servedAnchor(), laterDay)} days`
    );

    await expect(soonerRow.getByTestId('upcoming-date-badge')).toHaveText(
      'Birthday'
    );
    // The age the occurrence makes, counted from the year it falls in — which
    // is the window's year, or the next one when the week spans New Year.
    await expect(laterRow.getByTestId('upcoming-date-badge')).toHaveText(
      `Birthday · turns ${Number(laterDay.slice(0, 4)) - 1990}`
    );
    await expect(laterRow.getByTestId('upcoming-date-when')).toHaveText(
      expectedWeekdayDate(laterDay)
    );

    // Each row links to its contact.
    await expect(
      laterRow.getByRole('link', {
        name: `${later.firstName} ${later.lastName}`,
      })
    ).toHaveAttribute('href', `/contacts/${later.id}`);
  });

  test('draws three rows and names the whole week, then reveals the rest in place (W32)', async ({
    authenticatedPage: page,
  }) => {
    const week = Array.from({ length: 5 }, (_, index) =>
      mockUpcomingDate(9201 + index, index + 1)
    );
    const dashboard = await mockDashboardSections(page, () => ({
      upcoming_dates: ready({
        window: MOCK_WINDOW,
        total: week.length,
        dates: week,
      }),
    }));
    await page.setViewportSize(DESKTOP);
    await openDashboard(page);

    const card = page.getByTestId('upcoming-dates-card');
    await expect(upcomingRows(page)).toHaveCount(3);
    await expect(
      upcomingList(page).getByRole('link', { name: 'Mocked Contact 9204' })
    ).toHaveCount(0);
    const showMore = card.getByRole('button', {
      name: 'Show all 5 this week',
    });
    await expect(showMore).toBeVisible();

    const urlBefore = page.url();
    const readsBefore = dashboard.served();
    await showMore.click();

    await expect(upcomingRows(page)).toHaveCount(5);
    await expect(
      upcomingList(page).getByRole('link', { name: 'Mocked Contact 9205' })
    ).toBeVisible();
    await expect(showMore).toHaveCount(0);
    expect(page.url()).toBe(urlBefore);
    expect(dashboard.served()).toBe(readsBefore);
  });

  test('says in one line that no dates are coming up (gap 2)', async ({
    authenticatedPage: page,
  }) => {
    await mockDashboardSections(page, () => ({}));
    await page.setViewportSize(DESKTOP);
    await openDashboard(page);

    const card = page.getByTestId('upcoming-dates-card');
    await expect(
      card.getByText('No important dates in the next seven days.')
    ).toBeVisible();
    await expect(upcomingList(page)).toBeAttached();
    await expect(upcomingRows(page)).toHaveCount(0);
    await expect(card.getByTestId('upcoming-dates-show-more')).toHaveCount(0);
    await expect(card.getByRole('alert')).toHaveCount(0);
  });
});

/**
 * Nothing pushes the page sideways at mobile width (ITER18-004 Phase 16,
 * **W3**).
 *
 * The agenda already has a test of this shape for its own row; this covers the
 * other two sections, and specifically the case a unit test **cannot** reach.
 * Overflow is a layout property and jsdom computes none, so RTL can only pin
 * that a wrapping utility is on the element — this measures the outcome. The
 * content is deliberately one long *unbroken* token rather than a long
 * sentence: `min-w-0` is on almost every element in these rows and does nothing
 * for an unbreakable word, which is why this is the case that finds the defect.
 */
test.describe('Home Dashboard — mobile layout (W3)', () => {
  /**
   * Long, and with nowhere to break — what a pasted identifier looks like.
   *
   * Fifty-odd characters rather than a hundred, because the contacts domain
   * caps a name at 100 and `createContacts` appends a uniqueness suffix of its
   * own. Still four times the width of the column it sits in at 375px, which is
   * all this needs.
   */
  const UNBROKEN = `Zzz${'x'.repeat(50)}`;

  /**
   * Longer, because a badge draws at `text-xs`: fifty characters there is only
   * about as wide as the column, so it would neither prove nor disprove the
   * badge fix. Eighty-odd is unambiguously wider than a 375px viewport, and
   * still inside the tag name's own hundred-character limit once the data
   * manager has appended its uniqueness suffix.
   */
  const UNBROKEN_TAG = `Zzz${'x'.repeat(80)}`;

  test('overflows nothing with a long task, journal, contact, date and tag', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);
    const dueDay = daysAfter(day, 2);

    const [contact] = await dataManager.createContacts([
      {
        firstName: UNBROKEN,
        lastName: UNBROKEN,
        importantDates: [
          {
            date_type: 'birthday',
            precision: 'full',
            year: 1990,
            month: Number(dueDay.slice(5, 7)),
            day: Number(dueDay.slice(8, 10)),
          },
        ],
      },
    ]);

    // An agenda event carrying a tag of the same shape (W15), so all three
    // sections are drawing something unbreakable when the page is measured —
    // and so a **badge** is among them. Badges are the case review found the
    // first attempt at this had missed: `Badge`'s own `whitespace-nowrap`
    // forbids the break `break-words` asks for, so the class went on and the
    // layout stayed broken. A tag rather than a custom date type only because
    // a custom type needs its own record seeded; the two share one override.
    const [tag] = await dataManager.createJournalTags([{ name: UNBROKEN_TAG }]);
    const [calendar] = await dataManager.createCalendars([
      { name: 'Mobile Overflow Cal', color: '#EC4899' },
    ]);
    const event = await createAgendaEvent(dataManager, day, {
      title: `Mobile overflow ${UNBROKEN}`,
      startTime: '09:00:00',
      endTime: '10:00:00',
      calendarId: calendar.id,
    });
    await dataManager.assignTagsToJournal(event.id, [tag.id]);

    const creating = await dataManager.createJournal({
      title: 'Mobile overflow journal it came from',
      content: 'Task anchor seeded for the mobile overflow check',
      event_date_range: {
        start: atUtc(day, '09:00:00'),
        end: atUtc(day, '10:00:00'),
      },
    });
    const dueJournal = await dataManager.createJournal({
      title: `Mobile overflow ${UNBROKEN}`,
      content: 'Task anchor seeded for the mobile overflow check',
      event_date_range: {
        start: atUtc(dueDay, '09:00:00'),
        end: atUtc(dueDay, '10:00:00'),
      },
    });
    await dataManager.createTask({
      creatingJournalId: creating.id,
      dueJournalId: dueJournal.id,
      text: `Mobile overflow ${UNBROKEN}`,
      contactIds: [contact.id],
    });

    await page.setViewportSize(MOBILE);
    await openDashboard(page);

    // Every section has to be drawing it, or the measurement proves nothing.
    for (const list of [
      "Today's agenda",
      TASKS_LIST_NAME,
      'Upcoming contact dates',
    ]) {
      await expect(
        page
          .getByRole('list', { name: list })
          .getByText(/^Zzzx+/, { exact: false })
          .first()
      ).toBeVisible();
    }

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);

    // And the badge is legible rather than merely contained. Review (PR #1435)
    // read the badge case as page overflow; it is not, because `w-fit` resolves
    // against the available width and `overflow-hidden` swallows the rest — so
    // a long tag name was **clipped in place** instead of pushing the page
    // sideways. That is invisible to the measurement above and to any test that
    // only checks a class is present, which is why it is asserted directly.
    const badge = page.getByTestId('agenda-entry-tags').getByText(/^Zzzx+/);
    await expect(badge).toBeVisible();
    const clipped = await badge.evaluate(node => ({
      scrollWidth: node.scrollWidth,
      clientWidth: node.clientWidth,
    }));
    expect(clipped.scrollWidth).toBeLessThanOrEqual(clipped.clientWidth);
  });
});

/**
 * Home Dashboard — the summary, generated end to end (ITER18-005 Phase 8)
 *
 * The card's three states from real data rather than served payloads. The e2e
 * stack's model is a stub: `ENABLE_TEST_DAILY_SUMMARY_STUB` makes
 * `DailySummaryService` answer with one fixed sentence instead of calling
 * Gemini, so a *generated* summary is reachable from a fixture.
 *
 * **Today's summary is one row shared by the whole run** — one e2e user, one
 * worker, one row per day — so no test inherits a state; each establishes the
 * one it asserts. Two consequences shape the helpers below:
 *
 * - A generation can be *refused*. Seeding a journal or a task invalidates the
 *   day asynchronously (outbox → relay → consumer), and an invalidation landing
 *   while a generation is running makes the persist guard keep the row pending
 *   (ITER18-005 Phase 7c). So a regeneration is pressed until its own response
 *   says `generated`, which is idempotent and level-triggered.
 * - The server's state is read from `GET /api/home-dashboard`, which never
 *   writes. The daily-summary read would *regenerate* what it was asked about.
 */

/** The sentence the stub model writes (`DAILY_SUMMARY_STUB_TEXT`). */
const STUB_SUMMARY_TEXT =
  'A stubbed daily summary: the end-to-end stack answers without an AI model.';

/** One W10 value, found by its label rather than by its position. */
function summaryStat(page: Page, label: string) {
  return page
    .getByTestId('dashboard-summary-stats')
    .locator('div')
    .filter({ has: page.locator('dt', { hasText: new RegExp(`^${label}$`) }) })
    .locator('dd');
}

/**
 * Press Regenerate until a regeneration comes back generated for
 * `journalCount` journals, and the card shows it.
 *
 * The response is what is asserted first, because the card can already be
 * showing an earlier generated summary: only the regeneration's own answer
 * says this press produced what the card then draws.
 */
async function regenerateUntilGenerated(page: Page, journalCount: number) {
  const button = page.getByRole('button', { name: /regenerate/i });
  await expect(async () => {
    await expect(button).toBeEnabled({ timeout: 5000 });
    const [response] = await Promise.all([
      page.waitForResponse(
        candidate =>
          candidate.url().includes('/api/journals/daily-summary/') &&
          candidate.url().endsWith('/regenerate') &&
          candidate.request().method() === 'POST',
        { timeout: 15000 }
      ),
      button.click({ timeout: 5000 }),
    ]);
    const body = (await response.json()) as DailySummaryResponse;
    expect(body.data?.attributes.status).toBe('generated');
    expect(body.data?.attributes.journal_count).toBe(journalCount);

    await expect(page.getByTestId('dashboard-summary-text')).toHaveText(
      STUB_SUMMARY_TEXT,
      { timeout: 5000 }
    );
    await expect(summaryStat(page, 'Journals')).toHaveText(
      String(journalCount),
      { timeout: 5000 }
    );
  }).toPass({ timeout: 90000 });
}

/** Today's summary state as the read-only dashboard endpoint reports it. */
async function servedSummaryState(page: Page) {
  const response = await page.request.get('/api/home-dashboard');
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as HomeDashboardResponse;
  return body.data.attributes.summary.data?.state;
}

/**
 * What an AI-unconfigured backend says about the summary, over a real page.
 *
 * One stack cannot be configured and unconfigured at once, and this one has
 * the stub on. So the three answers an unconfigured backend gives — an
 * unavailable summary section, and `data: null` from both the summary read and
 * the regeneration, which `test_daily_summary_stub_api.py` pins against the
 * real endpoints — are served here, while the agenda, tasks and upcoming dates
 * pass through from the real dashboard untouched.
 */
async function serveUnconfiguredSummary(page: Page) {
  await page.route('**/api/home-dashboard', async route => {
    const response = await route.fetch();
    const body = (await response.json()) as HomeDashboardResponse;
    body.data.attributes.summary = unavailableSection;
    await route.fulfill({ response, json: body });
  });
  const unconfigured = { data: null } satisfies DailySummaryResponse;
  await page.route('**/api/journals/daily-summary/**', route =>
    route.fulfill({ json: unconfigured })
  );
}

test.describe('Home Dashboard — the summary, generated end to end', () => {
  test('shows a generated summary on a quiet day with a task due, not the unavailable line (W7, W10)', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);

    // The day's journal count is part of what is asserted, and a full run holds
    // journals dated today that specs creating them through the UI leave behind.
    await dataManager.clearJournalsOn(day);

    // One journal today — the task's creating journal — and the task due two
    // days out: below the two journals any other day needs for a summary.
    await createDashboardTask(
      dataManager,
      day,
      'Summary quiet day confirm the booking'
    );

    await page.setViewportSize(DESKTOP);
    await openDashboard(page);

    await regenerateUntilGenerated(page, 1);
    await expect(page.getByTestId('dashboard-summary-unavailable')).toHaveCount(
      0
    );
    await expect(page.getByTestId('dashboard-summary-stats')).toBeVisible();
  });

  test('updates the card when a regeneration is requested (W6)', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);

    // The day's journal count is part of what is asserted, and a full run holds
    // journals dated today that specs creating them through the UI leave behind.
    await dataManager.clearJournalsOn(day);

    await createDashboardTask(
      dataManager,
      day,
      'Summary regenerate water the garden'
    );

    await page.setViewportSize(DESKTOP);
    await openDashboard(page);
    await regenerateUntilGenerated(page, 1);
    const urlBefore = page.url();

    // A second journal today changes the summary's inputs. Waiting for the
    // server to report today stale is what makes the invalidation it causes
    // land *before* the regeneration rather than during it.
    await dataManager.createJournal({
      title: 'Summary regenerate second journal today',
      content: 'Seeded to move the summary card key stats.',
      event_date_range: {
        start: atUtc(day, '14:00:00'),
        end: atUtc(day, '15:00:00'),
      },
    });
    await expect
      .poll(() => servedSummaryState(page), { timeout: 30000 })
      .toBe(GENERATING);

    await regenerateUntilGenerated(page, 2);
    expect(page.url()).toBe(urlBefore);
  });

  test('with AI unconfigured, says so in one quiet line while the agenda, tasks and dates still work (W9)', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const day = await anchorDay(page);

    const [calendar] = await dataManager.createCalendars([
      { name: 'Summary Unconfigured Cal', color: '#0EA5E9' },
    ]);
    const standup = await createAgendaEvent(dataManager, day, {
      title: 'Summary unconfigured standup',
      startTime: '09:00:00',
      endTime: '09:30:00',
      calendarId: calendar.id,
    });
    const { task } = await createDashboardTask(
      dataManager,
      day,
      'Summary unconfigured post the parcel'
    );
    const [friend] = await dataManager.createContacts([
      {
        firstName: 'Summary',
        lastName: 'Unconfigured',
        importantDates: [
          {
            date_type: BIRTHDAY,
            precision: 'day_month',
            ...monthAndDay(daysAfter(day, 3)),
          },
        ],
      },
    ]);

    await serveUnconfiguredSummary(page);
    await page.setViewportSize(DESKTOP);
    await openDashboard(page);

    await expect(page.getByTestId('dashboard-summary-unavailable')).toHaveText(
      'No summary today — everything below still works.'
    );
    await expect(
      page.getByRole('button', { name: /regenerate/i })
    ).toBeEnabled();
    await expect(page.getByTestId('dashboard-summary-stats')).toHaveCount(0);

    // The three evidence sections, each drawing what was seeded for it.
    await expect(agendaRow(page, standup)).toBeVisible();
    await expect(upcomingRowFor(page, friend)).toBeVisible();
    const row = tasksList(page).getByTestId(`dashboard-task-${task.id}`);
    await expect(row).toBeVisible();

    // And working, not merely drawn: the one action the page offers still acts.
    const write = writeFor(page, task);
    await row.getByRole('button', { name: 'Mark done' }).click();
    await expect(row).toHaveCount(0);
    await write;
    await expect(
      page.getByTestId('dashboard-summary-unavailable')
    ).toBeVisible();
  });
});
