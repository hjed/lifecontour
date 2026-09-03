import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';

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
        agenda: { status: 'ready', data: { entries: [] } },
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
