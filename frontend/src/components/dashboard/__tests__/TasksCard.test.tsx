/**
 * @jest-environment jsdom
 *
 * The tasks card (**W21**–**W27**): what is due in the coming week, read from
 * the dashboard payload the page already fetched.
 *
 * Rendered over the **real** `useHomeDashboard` hook against a routed `fetch`
 * mock rather than a mocked hook, as the agenda's, the summary's and the
 * upcoming-dates' tests are: what the card shows is derived from the section
 * envelope — ready with tasks, ready and empty, unavailable — and a card that
 * ignored `status` would pass against a mocked hook.
 *
 * This file replaces the tasks section's entry in `section-cards.test.tsx`,
 * whose docstring nominated this phase for exactly that: a card with states of
 * its own is tested beside them rather than against a shared shell checklist.
 */

import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '@/test-utils';
import { TasksCard } from '../TasksCard';
import { DashboardSectionStatus } from '@/lib/api/home-dashboard';
import type {
  DashboardSection,
  HomeDashboardResponse,
  HomeDashboardTask,
  HomeDashboardTasks,
} from '@/lib/api/home-dashboard';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const DASHBOARD_URL = '/api/home-dashboard';
const TITLE = 'Tasks';
const DESCRIPTION =
  'Due in the next seven days, soonest first. Tick them off here.';
const LIST_NAME = 'Tasks due in the next seven days';
const EMPTY_LINE = 'Nothing due in the next seven days.';
const ANCHOR_DATE = '2026-07-31';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: { id: '1', email: 'test@example.com', name: 'Test User' },
};

function dashboardTask(
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

/** Six tasks, in the order the server settled on — one past the cap. */
const SIX_TASKS = [1, 2, 3, 4, 5, 6].map(id =>
  dashboardTask({ task_id: id, days_away: id - 1 })
);

function tasksSection(tasks: HomeDashboardTask[]): HomeDashboardTasks {
  return {
    // The window is `start_date` plus `days_ahead`; a fixture whose three
    // fields disagree describes a week the endpoint cannot send.
    window: { start_date: ANCHOR_DATE, end_date: '2026-08-07', days_ahead: 7 },
    // Named on the wire and derived from the same list here, because the
    // server does not cap: total is what Phase 15's show-more will display.
    total: tasks.length,
    tasks,
  };
}

function dashboardDocument(
  section: DashboardSection<HomeDashboardTasks>
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        agenda: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        tasks: section,
        upcoming_dates: {
          status: DashboardSectionStatus.READY,
          data: {
            window: {
              start_date: ANCHOR_DATE,
              end_date: '2026-08-07',
              days_ahead: 7,
            },
            total: 0,
            dates: [],
          },
        },
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: 'Australia/Sydney' } },
  };
}

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

function serveSection(section: DashboardSection<HomeDashboardTasks>) {
  routeFetch(() =>
    Promise.resolve({
      ok: true,
      json: async () => dashboardDocument(section),
    } as Response)
  );
}

function serveReady(tasks: HomeDashboardTask[]) {
  serveSection({
    status: DashboardSectionStatus.READY,
    data: tasksSection(tasks),
  });
}

function tasksList() {
  return screen.getByRole('list', { name: LIST_NAME });
}

describe('TasksCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('with tasks in the window', () => {
    it('carries its wireframe title and description (W21)', async () => {
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByRole('heading', { level: 3, name: TITLE })
      ).toBeInTheDocument();
      expect(screen.getByText(DESCRIPTION)).toBeInTheDocument();
    });

    /**
     * **The cap lives here and nowhere else.** The server sends the whole
     * seven-day window with its `total` (Phase 13's settled shape), the card
     * draws five (**W22**), and Phase 15's show-more reveals the remainder
     * from data already held.
     */
    it('caps the list at five, as the specification requires', async () => {
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      const rows =
        await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(rows).toHaveLength(5);
      expect(screen.queryByText('Commitment 6')).not.toBeInTheDocument();
    });

    it("keeps the server's order and does not re-sort", async () => {
      // Due-journal date ascending, ties broken by task id, is the server's
      // rule and is pinned there. The card draws the list it is given.
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      const rows =
        await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(
        rows.map(
          row => within(row).getByTestId('dashboard-task-text').textContent
        )
      ).toEqual([
        'Commitment 1',
        'Commitment 2',
        'Commitment 3',
        'Commitment 4',
        'Commitment 5',
      ]);
    });

    it('draws no empty line while it holds rows', async () => {
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });

    /**
     * **W24** is *"an inline Done button on every row"*, and "every" is the
     * assertion: a card that mounted the action on the first row only would
     * look right in a screenshot and leave four commitments unactionable.
     */
    it('mounts an inline done action on every row (W24)', async () => {
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      const rows =
        await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      rows.forEach(row => {
        expect(
          within(row).getByTestId('dashboard-task-action-done')
        ).toBeInTheDocument();
      });
    });

    it('describes each row’s action by the commitment it acts on', async () => {
      serveReady([SIX_TASKS[0]!]);

      renderWithProviders(<TasksCard />);

      const group = await screen.findByRole('group', { name: 'Task actions' });
      const describedBy = group.getAttribute('aria-describedby');
      expect(describedBy).toBeTruthy();
      expect(document.getElementById(describedBy!)).toHaveTextContent(
        'Commitment 1'
      );
    });

    /**
     * **AC5**, at the level where a section could grow one: no overdue
     * section, counter or badge anywhere. The payload cannot express one —
     * lapsed tasks are excluded server-side and no row carries a status — and
     * this is what keeps a later phase from adding a count beside the header.
     */
    it('shows no overdue count, badge or section (AC5)', async () => {
      serveReady(SIX_TASKS);

      renderWithProviders(<TasksCard />);

      await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(screen.queryByText(/overdue/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/lapsed/i)).not.toBeInTheDocument();
    });
  });

  describe('with nothing to draw', () => {
    /**
     * Three reasons a list can be empty, kept apart on purpose. **Nothing due
     * this week** is a real answer and gets **W29**'s single line; a query
     * still **in flight** and a section that came back **unavailable** each
     * get a quiet line of their own, because "nothing due" would be a false
     * claim about either. Phase 16 replaces the latter two with the real
     * treatment (wireframe gap 9).
     */
    it('says in one line that nothing is due, reading as a good outcome (W29)', async () => {
      serveReady([]);

      renderWithProviders(<TasksCard />);

      expect(await screen.findByText(EMPTY_LINE)).toBeInTheDocument();
      // No error styling, no retry: W29 is a quiet line, not a failure.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /try again|retry/i })
      ).not.toBeInTheDocument();
    });

    it('does not claim nothing is due while the query is still in flight', () => {
      routeFetch(() => new Promise<Response>(() => {}));

      renderWithProviders(<TasksCard />);

      expect(screen.getByTestId('tasks-loading')).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });

    it('does not claim nothing is due when the section is unavailable', async () => {
      serveSection({ status: DashboardSectionStatus.UNAVAILABLE, data: null });

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByTestId('tasks-unavailable')
      ).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });

    it('reads as unavailable when the whole request fails', async () => {
      routeFetch(() => Promise.reject(new Error('network')));

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByTestId('tasks-unavailable')
      ).toBeInTheDocument();
    });

    /**
     * The guard the agenda and dates cards both carry, for the reason they
     * carry it: the type promises an array on every ready section, but a
     * payload that broke that used to throw out of render and take the
     * **whole page** with it. "Sections render independently" has to survive a
     * section that breaks its contract, not only one reporting itself
     * unavailable.
     */
    it('survives a ready section whose tasks are not an array', async () => {
      serveSection({
        status: DashboardSectionStatus.READY,
        data: { ...tasksSection([]), tasks: null as unknown as [] },
      });

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByTestId('tasks-unavailable')
      ).toBeInTheDocument();
    });

    it('keeps its labelled list in every state (W4)', async () => {
      serveReady([]);

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByRole('list', { name: LIST_NAME })
      ).toBeInTheDocument();
    });
  });
});
