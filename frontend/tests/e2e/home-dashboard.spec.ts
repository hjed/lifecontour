import type { Page } from '@playwright/test';
import { TestDataManager } from './data-management';
import { test, expect, type TestJournal } from './fixtures';

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

/** Open the dashboard and wait for its shell, not for the network to go quiet. */
async function openDashboard(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('home-dashboard-ready')).toBeVisible();
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
 * and deliberately so: `generated` and `generating` are produced by an AI
 * provider the e2e stack does not configure, so neither can be *created*
 * deterministically — only served. Each test installs its own mock for exactly
 * one state before navigating, which is what keeps every assertion
 * single-outcome; `journals-daily-summary.spec.ts` sets the same precedent for
 * the journals view's copy of this card.
 *
 * `unavailable` is the exception, and is mocked for a different reason: with no
 * AI configured it is the stack's *natural* answer, so an unmocked test would
 * pass — until another spec in the run leaves a summary row on the anchor day,
 * at which point it would fail for a reason that has nothing to do with this
 * card. Serving it keeps the state under the test's own control rather than the
 * suite's ordering. Proving the real endpoint reaches this rendering is the
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
/** The mocked day after the mocked anchor — what the disclosure labels itself with. */
const MOCK_TOMORROW = nextDay(SUMMARY_ANCHOR);

const REGENERATE_PATH = `**/api/journals/daily-summary/${SUMMARY_ANCHOR}/regenerate`;

const SUMMARY_PROSE = 'A quiet Wednesday. Two journals and one long walk.';
const REGENERATED_PROSE = 'A busier Wednesday after all. Three journals.';

type SummarySection =
  | {
      status: 'ready';
      data: {
        state: 'generated' | 'generating';
        summary_text: string | null;
        journal_count: number;
        event_count: number;
        contact_count: number;
        mood_average: number | null;
      };
    }
  | { status: 'unavailable'; data: null };

const generatedSection = (summaryText: string): SummarySection => ({
  status: 'ready',
  data: {
    state: 'generated',
    summary_text: summaryText,
    journal_count: 3,
    event_count: 2,
    contact_count: 4,
    mood_average: 7.5,
  },
});

const generatingSection: SummarySection = {
  status: 'ready',
  data: {
    state: 'generating',
    summary_text: null,
    journal_count: 3,
    event_count: 2,
    contact_count: 4,
    mood_average: 7.5,
  },
};

const unavailableSection: SummarySection = {
  status: 'unavailable',
  data: null,
};

/** The dashboard document, with the summary section under test. */
function dashboardBody(summary: SummarySection) {
  return {
    data: {
      type: 'home-dashboards',
      id: 'e2e-user',
      attributes: {
        summary,
        // `tomorrow` rides on every ready agenda (Phase 6). Omitting it here
        // served a payload the API cannot produce, and the tomorrow
        // disclosure beneath today's list is drawn from it.
        agenda: {
          status: 'ready',
          data: { entries: [], tomorrow: { date: MOCK_TOMORROW, entries: [] } },
        },
        tasks: { status: 'ready', data: {} },
        upcoming_dates: { status: 'ready', data: {} },
      },
    },
    meta: { anchor: { date: SUMMARY_ANCHOR, timezone: SUMMARY_TIMEZONE } },
  };
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
  await page.route('**/api/home-dashboard', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(dashboardBody(summaryFor())),
    });
  });
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
 * "today" comes from — the server, as the page-shell test above insists. The
 * residual window (midnight passing between seeding and the page's own read)
 * is inherent to a page that is always about today, and is not closed here.
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

/**
 * The calendar day after `day`, as `YYYY-MM-DD`.
 *
 * Stepped in UTC because the e2e user has no configured timezone, so the
 * backend's day boundaries — and therefore `agenda.tomorrow.date` — are UTC.
 * Built from the anchor the API gave rather than from a clock, for the reason
 * {@link anchorDay} exists.
 */
function nextDay(day: string): string {
  const stepped = new Date(`${day}T00:00:00Z`);
  stepped.setUTCDate(stepped.getUTCDate() + 1);
  return stepped.toISOString().slice(0, 10);
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

/** The agenda row for one seeded journal, by the id the row carries. */
function agendaRow(page: Page, journal: TestJournal) {
  return agendaList(page).getByTestId(`agenda-entry-${journal.id}`);
}

/** One mocked agenda entry, in the payload's shape. */
function mockEntry(journalId: number, title: string, startTime: string) {
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
    entries?: ReturnType<typeof mockEntry>[];
    tomorrow?: ReturnType<typeof mockEntry>[];
  } = {}
): Promise<void> {
  await page.route('**/api/home-dashboard', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          type: 'home-dashboards',
          id: 'e2e-user',
          attributes: {
            summary: unavailableSection,
            agenda: {
              status: 'ready',
              data: {
                entries: agenda.entries ?? [],
                tomorrow: {
                  date: MOCK_TOMORROW,
                  entries: agenda.tomorrow ?? [],
                },
              },
            },
            tasks: { status: 'ready', data: {} },
            upcoming_dates: { status: 'ready', data: {} },
          },
        },
        meta: { anchor: { date: SUMMARY_ANCHOR, timezone: SUMMARY_TIMEZONE } },
      }),
    });
  });
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
      await expect(trigger).toHaveText(/Tomorrow — /);
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
      const [holidayBox, retroBox] = await Promise.all([
        holidayRow.boundingBox(),
        retroRow.boundingBox(),
      ]);
      expect(holidayBox!.y).toBeLessThan(retroBox!.y);

      // In place: today is still on screen and nothing navigated.
      await expect(todayRow).toBeVisible();
      expect(page.url()).toBe(urlBefore);
      // The expanded panel is the only region the card adds, and it opens
      // beneath today's list rather than replacing it.
      const todayBox = await todayRow.boundingBox();
      expect(todayBox!.y).toBeLessThan(holidayBox!.y);

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
