/**
 * Fixtures for the home dashboard's payload.
 *
 * Three suites build the same envelope to exercise the tasks section — the
 * card, its inline action, and the task client's optimistic patch — and they
 * were three copies of the same thirty lines, which is what tipped SonarCloud's
 * duplication gate on ITER18-004 Phase 14. They are here for a better reason
 * than the gate, though: **a fixture repeated per suite is a contract claim
 * repeated per suite**, and the one thing this iteration keeps re-learning is
 * that a copied fixture inherits its neighbour's bugs (the mock windows whose
 * three fields could not describe any real week, corrected twice).
 *
 * Sections default to `unavailable` rather than to an empty ready payload, so
 * a suite says which sections it is actually about and no test leans on a
 * neighbour's shape by accident.
 */

import {
  DashboardSectionStatus,
  type DashboardSection,
  type HomeDashboardAgenda,
  type HomeDashboardResponse,
  type HomeDashboardSummary,
  type HomeDashboardTask,
  type HomeDashboardTasks,
  type HomeDashboardTasksWindow,
  type HomeDashboardUpcomingDates,
} from '@/lib/api/home-dashboard';

/** The day these fixtures are anchored on, in the user's configured zone. */
export const FIXTURE_ANCHOR_DATE = '2026-07-31';
export const FIXTURE_TIMEZONE = 'Australia/Sydney';

/**
 * The seven-day window both evidence sections are read for.
 *
 * `end_date` is `start_date` plus `days_ahead`, because a window whose three
 * fields disagree is one the endpoint cannot send — the defect two rounds of
 * review found in hand-written mocks.
 */
export const FIXTURE_WINDOW: HomeDashboardTasksWindow = {
  start_date: FIXTURE_ANCHOR_DATE,
  end_date: '2026-08-07',
  days_ahead: 7,
};

/** One task, as the payload sends one. */
export function dashboardTaskFixture(
  overrides: Partial<HomeDashboardTask> & { task_id: number }
): HomeDashboardTask {
  return {
    text: `Commitment ${overrides.task_id}`,
    due_journal: {
      id: 100 + overrides.task_id,
      title: `Journal ${overrides.task_id}`,
      date: '2026-08-01',
    },
    days_away: 1,
    contacts: [],
    ...overrides,
  };
}

/**
 * A ready tasks section holding these rows.
 *
 * `total` is the list's own length, because the server caps nothing: the whole
 * window travels so the show-more can reveal the remainder without a second
 * request. The show-more names the list's length, not `total`; a suite that
 * needs the two to disagree spreads its own `total` over this.
 */
export function tasksSectionFixture(
  tasks: readonly HomeDashboardTask[]
): HomeDashboardTasks {
  return { window: FIXTURE_WINDOW, total: tasks.length, tasks: [...tasks] };
}

/** A ready upcoming-dates section holding nothing, for suites not about it. */
export function emptyUpcomingDatesFixture(): HomeDashboardUpcomingDates {
  return { window: FIXTURE_WINDOW, total: 0, dates: [] };
}

const UNAVAILABLE = { status: DashboardSectionStatus.UNAVAILABLE, data: null };

interface HomeDashboardDocumentOverrides {
  readonly tasks?: DashboardSection<HomeDashboardTasks>;
  readonly upcoming_dates?: DashboardSection<HomeDashboardUpcomingDates>;
  readonly summary?: DashboardSection<HomeDashboardSummary>;
  readonly agenda?: DashboardSection<HomeDashboardAgenda>;
}

/** The whole envelope, with every section unavailable unless named. */
export function homeDashboardDocument(
  overrides: HomeDashboardDocumentOverrides = {}
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: overrides.summary ?? UNAVAILABLE,
        agenda: overrides.agenda ?? UNAVAILABLE,
        tasks: overrides.tasks ?? UNAVAILABLE,
        upcoming_dates: overrides.upcoming_dates ?? UNAVAILABLE,
      },
    },
    meta: {
      anchor: { date: FIXTURE_ANCHOR_DATE, timezone: FIXTURE_TIMEZONE },
    },
  };
}

/** The envelope with a ready tasks section holding these rows. */
export function dashboardWithTasks(
  tasks: readonly HomeDashboardTask[],
  overrides: HomeDashboardDocumentOverrides = {}
): HomeDashboardResponse {
  return homeDashboardDocument({
    ...overrides,
    tasks: {
      status: DashboardSectionStatus.READY,
      data: tasksSectionFixture(tasks),
    },
  });
}

/**
 * The tasks a cached or fetched document is currently showing.
 *
 * Reaches through the envelope the way the card does, so a test asserting on
 * the section is not also re-writing the path to it.
 */
export function tasksIn(
  document: HomeDashboardResponse | undefined
): HomeDashboardTask[] {
  const section = document?.data.attributes.tasks;
  const tasks =
    section?.status === DashboardSectionStatus.READY
      ? section.data?.tasks
      : undefined;
  return Array.isArray(tasks) ? tasks : [];
}

/**
 * The endpoint every dashboard card's fetch mock has to route.
 *
 * A literal rather than `API_ENDPOINTS.HOME_DASHBOARD`, deliberately.
 * `jest.setup.ts` mocks `@/lib/constants` with a subset that **omits** this
 * endpoint, so reading it here would resolve to `undefined` in every suite
 * that has not opted back into the real constants — and an `undefined` URL
 * fails no assertion, it just makes {@link dashboardRequestCount} return zero
 * for ever. A literal cannot go quiet that way.
 */
export const DASHBOARD_URL = '/api/home-dashboard';

/**
 * How many times the dashboard endpoint itself was asked.
 *
 * Here rather than per suite because it asserts a **shared** property of both
 * capped sections: the whole window travels in one payload precisely so a
 * show-more reveals the remainder without a second round trip, and a card that
 * refetched would still look right on screen. Counting the endpoint's own
 * calls is what makes that assertable — the session request the auth provider
 * makes goes through the same mock and must not be counted.
 */
export function dashboardRequestCount(
  mockFetch: jest.MockedFunction<typeof fetch>
): number {
  return mockFetch.mock.calls.filter(
    ([input]) => String(input) === DASHBOARD_URL
  ).length;
}

/**
 * Assert that an element can break a long unbroken word.
 *
 * **W3** forbids horizontal overflow at mobile widths, and the cases that
 * actually break it are free text arriving as one long token — a journal title
 * with no spaces, a pasted URL as a contact name, a tag somebody typed without
 * a break. `min-w-0` is everywhere in these rows and does **nothing** for that:
 * it lets a flex item shrink below its content, and an unbreakable word is not
 * shrinkable.
 *
 * Overflow is a layout property and jsdom computes no layout, so this pins the
 * *contract* rather than the outcome — a wrapping utility is present, and
 * nothing left on the element forbids the line break it needs. The outcome is
 * measured for real in `home-dashboard.spec.ts`, at mobile width, against
 * `scrollWidth`. Written against a set of acceptable utilities rather than one
 * literal, so swapping `break-words` for another that solves the same problem
 * is not a test failure.
 *
 * **The second half was added after review found the first half insufficient**
 * (PR #1435). `Badge`'s base styles carry `whitespace-nowrap`, and
 * `overflow-wrap: break-word` cannot break anything while a line break is
 * forbidden — so a badge with `break-words` bolted on satisfied the original
 * assertion while still taking the page sideways. `cn` removes the conflicting
 * class through tailwind-merge, so an element that really can wrap no longer
 * carries it.
 */
export function expectWrapsLongWords(element: HTMLElement | null): void {
  expect(element).not.toBeNull();
  const className = element?.className ?? '';
  expect(className).toMatch(
    /\b(break-words|break-all|wrap-anywhere|wrap-break-word|truncate)\b/
  );
  expect(className).not.toMatch(/\bwhitespace-nowrap\b/);
}
