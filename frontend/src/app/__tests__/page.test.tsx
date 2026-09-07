/**
 * @jest-environment jsdom
 *
 * The home dashboard's page shell (ITER18-004 Phase 3).
 *
 * These tests render the page over the **real** query hook against a routed
 * `fetch` mock rather than a mocked `useHomeDashboard`, because two of the
 * things the shell promises are only true at that level: that the page reads
 * its date from the server's anchor, and that the whole page costs one request
 * however many sections mount.
 */

import { screen, waitFor, within } from '@testing-library/react';
import { renderWithProviders } from '@/test-utils';
import HomePage from '@/app/page';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
} from '@/lib/api/home-dashboard';
import type {
  HomeDashboardAgendaEntry,
  HomeDashboardResponse,
  HomeDashboardTask,
  HomeDashboardTasks,
  HomeDashboardUpcomingDates,
} from '@/lib/api/home-dashboard';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

// Note: Next.js navigation is mocked globally in jest.setup.ts.

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const DASHBOARD_URL = '/api/home-dashboard';

/** Two of today's event journals, in the order the server sends them. */
const STANDUP: HomeDashboardAgendaEntry = {
  journal_id: 2,
  title: 'Standup',
  is_all_day: false,
  starts_at: '2026-07-29T09:00:00+10:00',
  ends_at: '2026-07-29T09:15:00+10:00',
  start_time: '09:00:00',
  end_time: '09:15:00',
  timezone: 'Australia/Sydney',
  location: null,
  calendar_color: '#336699',
  is_cancelled: false,
  tags: [],
  participants: [],
};
const LUNCH: HomeDashboardAgendaEntry = {
  ...STANDUP,
  journal_id: 3,
  title: 'Lunch with Sam',
  starts_at: '2026-07-29T12:30:00+10:00',
  ends_at: '2026-07-29T13:30:00+10:00',
  start_time: '12:30:00',
  end_time: '13:30:00',
  location: 'The cafe',
};

/**
 * The anchor every test renders against.
 *
 * Deliberately a fixed day in the past, so a shell that derived its date from
 * the browser's clock instead of `meta.anchor.date` could not pass.
 */
const ANCHOR_DATE = '2026-07-29';
const TOMORROW_DATE = '2026-07-30';
const ANCHOR_DISPLAY = 'Wednesday, 29 July 2026';

/**
 * The seven-day window both evidence sections are read for.
 *
 * Spelled out rather than derived, like the anchor above — but `end_date` is
 * genuinely `ANCHOR_DATE` plus `days_ahead`, which the first version of these
 * mocks got wrong by a day in both sections. A window whose three fields
 * disagree is a payload the endpoint cannot produce, and a mock that sends one
 * can hide a card relying on bounds the server never sends. Shared, because
 * the API sends the two sections one window: they cover the same week.
 */
const EMPTY_WINDOW = {
  start_date: ANCHOR_DATE,
  end_date: '2026-08-05',
  days_ahead: 7,
};

/**
 * A ready upcoming-dates section holding nothing.
 *
 * These tests are about the page's frame, not its dates, so the section is
 * ready-and-empty rather than absent: that is a real answer, and it keeps the
 * dates card in the one state the frame assertions expect.
 */
const EMPTY_UPCOMING_DATES: HomeDashboardUpcomingDates = {
  window: EMPTY_WINDOW,
  total: 0,
  dates: [],
};

/**
 * Nothing due this week, in the shape the endpoint really sends.
 *
 * Since ITER18-004 Phase 13 the section carries a window and a total, so a
 * ready one holding `{}` is a broken contract rather than a quiet week, and
 * since Phase 14 the card reads it — a section that under-described itself
 * would now draw the wrong thing rather than nothing.
 */
const EMPTY_TASKS: HomeDashboardTasks = {
  window: EMPTY_WINDOW,
  total: 0,
  tasks: [],
};

function dashboardDocument(): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: {
          status: DashboardSectionStatus.READY,
          data: {
            state: DashboardSummaryState.GENERATED,
            summary_text: 'A quiet Wednesday.',
            journal_count: 3,
            event_count: 2,
            contact_count: 4,
            mood_average: 7.5,
          },
        },
        agenda: {
          status: DashboardSectionStatus.READY,
          data: { entries: [], tomorrow: { date: TOMORROW_DATE, entries: [] } },
        },
        tasks: { status: DashboardSectionStatus.READY, data: EMPTY_TASKS },
        upcoming_dates: {
          status: DashboardSectionStatus.READY,
          data: EMPTY_UPCOMING_DATES,
        },
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: 'Australia/Sydney' } },
  };
}

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: {
    id: '1',
    email: 'test@example.com',
    name: 'Test User',
  },
};

/**
 * Route `fetch` by URL: the dashboard gets `dashboard`, everything else — the
 * `AuthProvider`'s session check — gets an authenticated user.
 */
function routeFetch(dashboard: () => Promise<Response>) {
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    if (String(input) === DASHBOARD_URL) {
      return dashboard();
    }
    return Promise.resolve({
      ok: true,
      json: async () => AUTHENTICATED_SESSION,
    } as Response);
  });
}

function respondWithDashboard() {
  routeFetch(() =>
    Promise.resolve({
      ok: true,
      json: async () => dashboardDocument(),
    } as Response)
  );
}

/** Render the page and wait for the shell to be on screen. */
async function renderHomePage() {
  renderWithProviders(<HomePage />);
  return screen.findByTestId('home-dashboard-ready');
}

/**
 * The three evidence sections, in the order the DOM holds them.
 *
 * Scoped to the grid rather than the page: the summary card is a labelled
 * region of its own (**W5**), and in a real browser the app chrome contributes
 * another (the toast area), so an unscoped role query counts more than three.
 */
function sectionNames(): string[] {
  return within(screen.getByTestId('dashboard-sections'))
    .getAllByRole('region')
    .map(
      section => section.getAttribute('aria-label') ?? headingTextOf(section)
    )
    .filter((name): name is string => Boolean(name));
}

function headingTextOf(section: HTMLElement): string | null {
  const labelledBy = section.getAttribute('aria-labelledby');
  if (!labelledBy) {
    return null;
  }
  return document.getElementById(labelledBy)?.textContent ?? null;
}

describe('HomePage — the dashboard shell', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    respondWithDashboard();
  });

  describe('Page header (W2)', () => {
    it('is headed "Today"', async () => {
      await renderHomePage();

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('Today');
    });

    it("shows the server's anchor day in full, not the browser's today", async () => {
      await renderHomePage();

      expect(
        await screen.findByText(new RegExp(ANCHOR_DISPLAY))
      ).toBeInTheDocument();
    });

    it('carries the framing line that says what the page is for', async () => {
      await renderHomePage();

      expect(
        await screen.findByText(
          /your day, what is coming up, and what you said you would do/i
        )
      ).toBeInTheDocument();
    });

    it('has exactly one level-1 heading', async () => {
      await renderHomePage();

      expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    });
  });

  describe('Section grid (W3, W4)', () => {
    it('renders the three evidence sections in wireframe order', async () => {
      await renderHomePage();

      expect(sectionNames()).toEqual(['Agenda', 'Tasks', 'Upcoming dates']);
    });

    it('labels each section with a visually hidden heading', async () => {
      await renderHomePage();

      for (const name of ['Agenda', 'Tasks', 'Upcoming dates']) {
        const heading = screen.getByRole('heading', { level: 2, name });
        expect(heading).toHaveClass('sr-only');
      }
    });

    it('gives each section a labelled list container', async () => {
      await renderHomePage();

      for (const name of [
        "Today's agenda",
        'Tasks due in the next seven days',
        'Upcoming contact dates',
      ]) {
        expect(screen.getByRole('list', { name })).toBeInTheDocument();
      }
    });

    it('stacks to one column below lg and sizes its columns independently', async () => {
      const ready = await renderHomePage();

      const grid = ready.querySelector('[data-testid="dashboard-sections"]');
      expect(grid).toHaveClass(
        'grid',
        'grid-cols-1',
        'lg:grid-cols-3',
        'items-start'
      );
    });

    it('adds no container of its own inside the layout chrome (W1)', async () => {
      // The root layout already supplies `.container.mx-auto.px-4.py-6`; a
      // second container nested inside it is the likeliest source of the
      // horizontal overflow W3 forbids.
      const ready = await renderHomePage();

      expect(ready.querySelector('.container')).toBeNull();
      expect(ready).not.toHaveClass('container');
    });
  });

  describe('The retired placeholder', () => {
    it.each([
      'Calendar',
      'Photos',
      'AI Integration',
      'System Status',
      'Personal Management System',
      'Your personal CRM and journal with AI integration',
      'Monitor system health and integration status.',
      'MCP protocol support for AI assistants to access and manage your data.',
    ])('no longer renders the placeholder text %s', async text => {
      await renderHomePage();

      expect(screen.queryByText(text)).not.toBeInTheDocument();
    });
  });

  describe('One round trip', () => {
    it('fetches the dashboard once for the whole page', async () => {
      await renderHomePage();

      await waitFor(() =>
        expect(screen.getByText(new RegExp(ANCHOR_DISPLAY))).toBeInTheDocument()
      );

      const dashboardCalls = mockFetch.mock.calls.filter(
        ([input]) => String(input) === DASHBOARD_URL
      );
      expect(dashboardCalls).toHaveLength(1);
    });
  });

  describe('Shell resilience', () => {
    it('renders its header and all three sections while the dashboard is still loading', async () => {
      routeFetch(() => new Promise<Response>(() => {}));

      await renderHomePage();

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        'Today'
      );
      expect(sectionNames()).toEqual(['Agenda', 'Tasks', 'Upcoming dates']);
    });

    it('renders the sections when the dashboard request fails', async () => {
      // Per-section unavailable states are Phase 16's; what this pins is that
      // a failed request does not take the page down with it.
      routeFetch(() =>
        Promise.resolve({
          ok: false,
          json: async () => ({ errors: [{ detail: 'Session expired' }] }),
        } as Response)
      );

      await renderHomePage();

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        'Today'
      );
      expect(sectionNames()).toEqual(['Agenda', 'Tasks', 'Upcoming dates']);
    });
  });

  describe('The summary card (W5)', () => {
    it('sits between the page header and the section grid', async () => {
      const ready = await renderHomePage();

      const card = await screen.findByTestId('dashboard-summary-card');
      const grid = screen.getByTestId('dashboard-sections');
      const header = screen.getByRole('heading', { level: 1 });

      // `compareDocumentPosition` reads DOM order, which is the order a
      // screen reader and a stacked mobile layout both follow.
      expect(
        header.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(
        card.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(ready).toContainElement(card);
    });

    it("renders today's summary from the payload the page already fetched", async () => {
      await renderHomePage();

      expect(
        await screen.findByTestId('dashboard-summary-text')
      ).toHaveTextContent('A quiet Wednesday.');
    });

    it('still costs one dashboard request with the card mounted', async () => {
      await renderHomePage();

      await screen.findByTestId('dashboard-summary-text');

      const dashboardCalls = mockFetch.mock.calls.filter(
        ([input]) => String(input) === DASHBOARD_URL
      );
      expect(dashboardCalls).toHaveLength(1);
    });

    it('leaves the three evidence sections rendering when the summary is unavailable', async () => {
      routeFetch(() =>
        Promise.resolve({
          ok: true,
          json: async () => {
            const document = dashboardDocument();
            document.data.attributes.summary = {
              status: DashboardSectionStatus.UNAVAILABLE,
              data: null,
            };
            return document;
          },
        } as Response)
      );

      await renderHomePage();

      expect(
        await screen.findByTestId('dashboard-summary-unavailable')
      ).toBeInTheDocument();
      expect(sectionNames()).toEqual(['Agenda', 'Tasks', 'Upcoming dates']);
    });
  });

  /**
   * The specification asks for independence in **both** directions: a failed
   * summary must not prevent the agenda from displaying, *and vice versa*.
   * Until the agenda card read the payload, the second direction was not
   * falsifiable — an unavailable `agenda` envelope could not affect anything
   * the page rendered. Now it can, so both directions are asserted with data
   * on the surviving side, which is what makes each a real claim.
   */
  describe('Sections render independently', () => {
    it('renders the agenda entries when the summary is unavailable', async () => {
      routeFetch(() =>
        Promise.resolve({
          ok: true,
          json: async () => {
            const document = dashboardDocument();
            document.data.attributes.summary = {
              status: DashboardSectionStatus.UNAVAILABLE,
              data: null,
            };
            document.data.attributes.agenda = {
              status: DashboardSectionStatus.READY,
              data: {
                entries: [STANDUP, LUNCH],
                tomorrow: { date: TOMORROW_DATE, entries: [] },
              },
            };
            return document;
          },
        } as Response)
      );

      await renderHomePage();

      expect(
        await screen.findByTestId('dashboard-summary-unavailable')
      ).toBeInTheDocument();
      const agenda = screen.getByRole('list', { name: "Today's agenda" });
      expect(
        within(agenda)
          .getAllByRole('listitem')
          .map(row => within(row).getByRole('link').textContent)
      ).toEqual(['Standup', 'Lunch with Sam']);
    });

    it('renders the summary when the agenda is unavailable', async () => {
      routeFetch(() =>
        Promise.resolve({
          ok: true,
          json: async () => {
            const document = dashboardDocument();
            document.data.attributes.agenda = {
              status: DashboardSectionStatus.UNAVAILABLE,
              data: null,
            };
            return document;
          },
        } as Response)
      );

      await renderHomePage();

      expect(
        await screen.findByTestId('dashboard-summary-text')
      ).toHaveTextContent('A quiet Wednesday.');
      expect(await screen.findByTestId('agenda-unavailable')).toBeVisible();
      expect(
        screen.queryByText('Nothing scheduled today.')
      ).not.toBeInTheDocument();
      expect(sectionNames()).toEqual(['Agenda', 'Tasks', 'Upcoming dates']);
    });

    it('still costs one dashboard request with the agenda card reading it', async () => {
      routeFetch(() =>
        Promise.resolve({
          ok: true,
          json: async () => {
            const document = dashboardDocument();
            document.data.attributes.agenda = {
              status: DashboardSectionStatus.READY,
              data: {
                entries: [STANDUP],
                tomorrow: { date: TOMORROW_DATE, entries: [] },
              },
            };
            return document;
          },
        } as Response)
      );

      await renderHomePage();
      await screen.findByRole('link', { name: 'Standup' });
      await screen.findByTestId('dashboard-summary-text');

      const dashboardCalls = mockFetch.mock.calls.filter(
        ([input]) => String(input) === DASHBOARD_URL
      );
      expect(dashboardCalls).toHaveLength(1);
    });
  });

  describe('Tasks section (W22)', () => {
    /**
     * The rows are the tasks card's own subject and are asserted in
     * `TasksCard.test.tsx`. What belongs here is that they reach the page
     * *inside their own section* — the three columns are independent, and a
     * row rendering into the wrong one is a layout failure no card test can
     * see — and that reading them still costs the page one request.
     */
    const DUE_TASK: HomeDashboardTask = {
      task_id: 31,
      text: 'Send the deposit receipt',
      due_journal: { id: 44, title: 'Friday planning', date: '2026-08-01' },
      days_away: 3,
      contacts: [],
    };

    function respondWithTasks() {
      routeFetch(() =>
        Promise.resolve({
          ok: true,
          json: async () => {
            const document = dashboardDocument();
            document.data.attributes.tasks = {
              status: DashboardSectionStatus.READY,
              data: { ...EMPTY_TASKS, total: 1, tasks: [DUE_TASK] },
            };
            return document;
          },
        } as Response)
      );
    }

    it('draws the week\u2019s tasks inside the tasks section', async () => {
      respondWithTasks();

      await renderHomePage();

      const [, tasks] = within(
        screen.getByTestId('dashboard-sections')
      ).getAllByRole('region');
      expect(
        await within(tasks).findByText('Send the deposit receipt')
      ).toBeInTheDocument();
      expect(
        within(tasks).getByRole('link', { name: 'Friday planning' })
      ).toHaveAttribute('href', '/journals/44');
    });

    it('still costs one dashboard request with the tasks card reading it', async () => {
      respondWithTasks();

      await renderHomePage();
      await screen.findByText('Send the deposit receipt');
      await screen.findByTestId('dashboard-summary-text');

      const dashboardCalls = mockFetch.mock.calls.filter(
        ([input]) => String(input) === DASHBOARD_URL
      );
      expect(dashboardCalls).toHaveLength(1);
    });
  });

  describe('Section cards', () => {
    it('each card carries its own wireframe header', async () => {
      await renderHomePage();

      const [agenda, tasks, dates] = within(
        screen.getByTestId('dashboard-sections')
      ).getAllByRole('region');

      // The visible title is the card's own heading, one level below the
      // section's hidden h2 — W4's "visible title provided by the card header".
      expect(
        within(agenda).getByRole('heading', { level: 3, name: 'Agenda' })
      ).toBeInTheDocument();
      expect(
        within(agenda).getByText(
          "Today's schedule in time order, all-day items first."
        )
      ).toBeInTheDocument();

      expect(
        within(tasks).getByRole('heading', { level: 3, name: 'Tasks' })
      ).toBeInTheDocument();
      expect(
        within(tasks).getByText(
          'Due in the next seven days, soonest first. Tick them off here.'
        )
      ).toBeInTheDocument();

      expect(
        within(dates).getByRole('heading', {
          level: 3,
          name: 'Upcoming dates',
        })
      ).toBeInTheDocument();
      expect(
        within(dates).getByText(
          'Important dates for your contacts over the next seven days.'
        )
      ).toBeInTheDocument();
    });
  });
});
