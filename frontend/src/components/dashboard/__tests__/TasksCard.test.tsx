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
 *
 * **The show-more is asserted against the request count as well as the DOM**
 * (**W28**). The whole seven-day window travels in the payload precisely so
 * revealing the remainder costs no second round trip, and a card that
 * refetched would still look right on screen.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test-utils';
import {
  DASHBOARD_URL,
  dashboardRequestCount,
  dashboardTaskFixture,
  emptyUpcomingDatesFixture,
  homeDashboardDocument,
  tasksSectionFixture,
} from '@/test-utils/home-dashboard';
import { TasksCard } from '../TasksCard';
import { DashboardSectionStatus } from '@/lib/api/home-dashboard';
import { TaskStatus } from '@/types/tasks';
import type {
  DashboardSection,
  HomeDashboardResponse,
  HomeDashboardTask,
  HomeDashboardTasks,
} from '@/lib/api/home-dashboard';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

// The inline done action toasts on both paths. Nothing here asserts on it —
// `DashboardTaskActions.test.tsx` owns that — but a real toast outside a
// `<Toaster/>` is noise this suite has no reason to carry.
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const TITLE = 'Tasks';
const DESCRIPTION =
  'Due in the next seven days, soonest first. Tick them off here.';
const LIST_NAME = 'Tasks due in the next seven days';
const EMPTY_LINE = 'Nothing due in the next seven days.';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: { id: '1', email: 'test@example.com', name: 'Test User' },
};

const dashboardTask = dashboardTaskFixture;

/** `count` tasks, in the order the server settled on: soonest first. */
function dashboardTasks(count: number): HomeDashboardTask[] {
  return Array.from({ length: count }, (_, index) =>
    dashboardTask({ task_id: index + 1, days_away: index })
  );
}

/** Exactly the cap: the window fits and nothing is hidden. */
const FIVE_TASKS = dashboardTasks(5);

/** One past the cap. */
const SIX_TASKS = dashboardTasks(6);

/** Seven — the count **W28** writes its button out with. */
const SEVEN_TASKS = dashboardTasks(7);

const tasksSection = tasksSectionFixture;

function dashboardDocument(
  section: DashboardSection<HomeDashboardTasks>
): HomeDashboardResponse {
  return homeDashboardDocument({
    tasks: section,
    upcoming_dates: {
      status: DashboardSectionStatus.READY,
      data: emptyUpcomingDatesFixture(),
    },
  });
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

function taskRows() {
  return within(tasksList()).queryAllByTestId(/^dashboard-task-\d+$/);
}

function showMore() {
  return screen.queryByRole('button', { name: /show all/i });
}

/**
 * A dashboard that answers the way the server would once a row is ticked off.
 *
 * The seam between this phase's cap and Phase 14's optimistic removal cannot
 * be asserted against a **static** payload: ticking a row refetches the
 * dashboard, and a mock that kept serving the original list would put the row
 * straight back and the test would be about the fixture rather than the card.
 * So the tick is applied here too, which is what a real backend does.
 */
function serveTickableTasks(initial: readonly HomeDashboardTask[]) {
  let tasks = [...initial];

  mockFetch.mockImplementation(
    (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === DASHBOARD_URL) {
        return Promise.resolve({
          ok: true,
          json: async () =>
            dashboardDocument({
              status: DashboardSectionStatus.READY,
              data: tasksSection(tasks),
            }),
        } as Response);
      }

      const tick = /^\/api\/tasks\/(\d+)$/.exec(url);
      if (tick && init?.method === 'PATCH') {
        const taskId = Number(tick[1]);
        tasks = tasks.filter(task => task.task_id !== taskId);
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            data: {
              type: 'tasks',
              id: String(taskId),
              attributes: { status: TaskStatus.DONE },
            },
          }),
        } as Response);
      }

      return Promise.resolve({
        ok: true,
        json: async () => AUTHENTICATED_SESSION,
      } as Response);
    }
  );
}

/**
 * Tick the row drawn at `position` off.
 *
 * The click is awaited but the write is not: what follows it — the optimistic
 * removal, the response, the refetch — is what the caller is asserting, so it
 * waits on the section rather than on the mutation.
 */
async function tickOff(
  user: ReturnType<typeof userEvent.setup>,
  position: number
) {
  const row = taskRows()[position] as HTMLElement;
  await user.click(within(row).getByTestId('dashboard-task-action-done'));
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

  /**
   * **W28**: the remainder of the seven-day window, revealed in place.
   *
   * The server caps nothing — the whole window travels with its `total` — so
   * the cap is the card's and the reveal costs no second request. That last
   * property is the one worth asserting against the **request count**: a card
   * that refetched would look identical on screen.
   */
  describe('revealing the rest of the window (W28)', () => {
    it('names the whole window on the show-more, not what is hidden', async () => {
      serveReady(SEVEN_TASKS);

      renderWithProviders(<TasksCard />);

      expect(
        await screen.findByRole('button', { name: /show all/i })
      ).toHaveTextContent('Show all 7 due this week');
    });

    it('reveals the remainder in place', async () => {
      serveReady(SEVEN_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      expect(taskRows()).toHaveLength(7);
    });

    it('costs no second request to reveal them', async () => {
      serveReady(SEVEN_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );
      expect(taskRows()).toHaveLength(7);

      expect(dashboardRequestCount(mockFetch)).toBe(1);
    });

    /**
     * **W24** is *"an inline Done button on every row"*, and the rows the
     * show-more reveals are rows. A card that mounted the actions against the
     * capped slice rather than against what it draws would leave the revealed
     * remainder unactionable — which looks right until someone expands.
     */
    it('mounts an inline done action on every revealed row', async () => {
      serveReady(SEVEN_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      const rows = taskRows();
      expect(rows).toHaveLength(7);
      rows.forEach(row => {
        expect(
          within(row).getByTestId('dashboard-task-action-done')
        ).toBeInTheDocument();
      });
    });

    it('withdraws the show-more once everything is shown', async () => {
      serveReady(SEVEN_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      // Withdrawn rather than turned into a "Show less": W28 describes one
      // control, and the upcoming-dates show-more settled the same way.
      expect(showMore()).not.toBeInTheDocument();
    });

    it('offers no show-more when the window fits', async () => {
      serveReady(FIVE_TASKS);

      renderWithProviders(<TasksCard />);

      await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(taskRows()).toHaveLength(5);
      expect(showMore()).not.toBeInTheDocument();
    });

    /**
     * **AC3's second half.** Expansion is component state and is deliberately
     * neither persisted nor put in the URL, so the next visit is five rows
     * again — the briefing page opens on the next five things, however long
     * the last visit spent reading the rest of the week.
     */
    it('comes back to five rows on the next load', async () => {
      serveReady(SEVEN_TASKS);
      const user = userEvent.setup();

      const first = renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );
      expect(taskRows()).toHaveLength(7);
      first.unmount();

      renderWithProviders(<TasksCard />);

      await within(tasksList()).findAllByTestId(/^dashboard-task-\d+$/);
      expect(taskRows()).toHaveLength(5);
      expect(showMore()).toBeInTheDocument();
    });
  });

  /**
   * Where this phase's cap meets Phase 14's optimistic removal.
   *
   * Ticking a row changes the very list the cap is measured against, and
   * neither direction is obvious from either phase on its own. The dashboard
   * mock applies the tick too, so the refetch that follows the write answers
   * the way the server would rather than putting the row back.
   */
  describe('when a row is ticked off beneath it', () => {
    it('withdraws the show-more once the list fits again', async () => {
      serveTickableTasks(SIX_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await screen.findByRole('button', { name: /show all/i });
      await tickOff(user, 0);

      // The sixth is promoted into view by the row leaving, and there is
      // nothing left to reveal.
      await waitFor(() => expect(taskRows()).toHaveLength(5));
      expect(screen.getByText('Commitment 6')).toBeInTheDocument();
      await waitFor(() => expect(showMore()).not.toBeInTheDocument());
    });

    it('keeps the remainder revealed when the list was expanded', async () => {
      serveTickableTasks(SEVEN_TASKS);
      const user = userEvent.setup();

      renderWithProviders(<TasksCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );
      await tickOff(user, 0);

      // Six left, all still drawn: a write must not collapse the section back
      // under the user, and the button must not return to offer what is
      // already on screen.
      await waitFor(() => expect(taskRows()).toHaveLength(6));
      expect(showMore()).not.toBeInTheDocument();
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

    /**
     * **W29 is an icon *and* a line**, and the icon is half of what makes it
     * read as a good outcome rather than an absence. A check, specifically —
     * the section's own word for "done" — decorative, because the sentence
     * beside it already says the whole thing.
     */
    it('draws the check icon above its empty line (W29)', async () => {
      serveReady([]);

      renderWithProviders(<TasksCard />);

      const icon = (await screen.findByText(EMPTY_LINE))
        .closest('div')
        ?.querySelector('svg');
      expect(icon).toHaveClass('lucide-circle-check');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });

    it('offers no show-more when nothing is due', async () => {
      serveReady([]);

      renderWithProviders(<TasksCard />);

      await screen.findByText(EMPTY_LINE);
      expect(showMore()).not.toBeInTheDocument();
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
