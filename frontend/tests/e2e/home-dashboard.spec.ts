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
    test('renders the dashboard at the root route, headed Today', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Today');
    });

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

    test('says what the page is for', async ({ authenticatedPage: page }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByText(
          /your day, what is coming up, and what you said you would do/i
        )
      ).toBeVisible();
    });
  });

  test.describe('The three evidence sections', () => {
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

    test('gives each section a labelled list for its entries', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      for (const label of [
        "Today's agenda",
        'Tasks due in the next seven days',
        'Upcoming contact dates',
      ]) {
        await expect(page.getByRole('list', { name: label })).toBeAttached();
      }
    });

    test('shows each section header from the wireframe', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize(DESKTOP);
      await openDashboard(page);

      await expect(
        page.getByText("Today's schedule in time order, all-day items first.")
      ).toBeVisible();
      await expect(
        page.getByText(
          'Due in the next seven days, soonest first. Tick them off here.'
        )
      ).toBeVisible();
      await expect(
        page.getByText(
          'Important dates for your contacts over the next seven days.'
        )
      ).toBeVisible();
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
