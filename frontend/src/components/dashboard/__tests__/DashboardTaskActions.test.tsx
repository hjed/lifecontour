/**
 * @jest-environment jsdom
 *
 * The inline done action on a dashboard task row (**W24**).
 *
 * The wireframe draws one button here and only one, because everything on the
 * dashboard is not-done: completion is the only status move a row on this page
 * can make. The journal surface offers the way back and the cancel beside it;
 * delete and retarget are journal-only (wireframe gaps 8 and 10), because the
 * dashboard is where a commitment is *reminded of* rather than worked with.
 *
 * Three things these assert that the phase's acceptance criteria rest on:
 *
 * - **Acting on it must not navigate away** — W24 says so in terms, and it is
 *   the whole point of an inline action on a briefing page.
 * - **The row leaves the section before the response lands**, and comes back
 *   if the write fails. The patch itself lives in `useUpdateTask` and is
 *   asserted there; these drive it through the button a user presses.
 * - **Ticking a task refetches the dashboard and nothing else** — in
 *   particular no summary is requested or regenerated underneath the user
 *   (**AC6**, the client half of ITER18-005 Phase 7's contract).
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { DashboardTaskActions } from '../DashboardTaskActions';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { homeDashboardKeys } from '@/lib/api/home-dashboard';
import { DashboardSectionStatus } from '@/lib/api/home-dashboard';
import type {
  HomeDashboardResponse,
  HomeDashboardTask,
} from '@/lib/api/home-dashboard';
import { taskTextId } from '@/lib/dashboard-tasks-display';
import { TaskStatus } from '@/types/tasks';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` mocks `@/lib/constants` down to the endpoints the auth tests
// need, which would leave `API_ENDPOINTS.TASKS` undefined and every mutation
// here throwing before it reached `fetch`.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const TASK_ID = 12;
const TASK_TEXT = 'Send Priya the deposit receipt';
const ANCHOR = '2026-07-31';

function okResponse(status: TaskStatus): Response {
  return {
    ok: true,
    status: 200,
    json: jest.fn().mockResolvedValue({
      data: { type: 'tasks', id: String(TASK_ID), attributes: { status } },
    }),
  } as unknown as Response;
}

function failureResponse(detail: string): Response {
  return {
    ok: false,
    status: 500,
    json: jest.fn().mockResolvedValue({
      errors: [{ status: '500', code: 'INTERNAL_ERROR', detail }],
    }),
  } as unknown as Response;
}

function dashboardTask(taskId: number): HomeDashboardTask {
  return {
    task_id: taskId,
    text: taskId === TASK_ID ? TASK_TEXT : `Commitment ${taskId}`,
    due_journal: {
      id: 40 + taskId,
      title: `Journal ${taskId}`,
      date: '2026-08-01',
    },
    days_away: 1,
    contacts: [],
  };
}

function dashboardDocument(tasks: HomeDashboardTask[]): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        agenda: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        tasks: {
          status: DashboardSectionStatus.READY,
          data: {
            window: {
              start_date: ANCHOR,
              end_date: '2026-08-07',
              days_ahead: 7,
            },
            total: tasks.length,
            tasks,
          },
        },
        upcoming_dates: {
          status: DashboardSectionStatus.UNAVAILABLE,
          data: null,
        },
      },
    },
    meta: { anchor: { date: ANCHOR, timezone: 'Australia/Sydney' } },
  };
}

/**
 * Render the action beside the text it acts on, as the card mounts it.
 *
 * The dashboard payload is seeded so the optimistic removal and its rollback
 * have something real to move rather than being asserted on a cache nothing
 * reads.
 */
function renderActions(taskId = TASK_ID) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(
    homeDashboardKeys.all,
    dashboardDocument([dashboardTask(TASK_ID), dashboardTask(99)])
  );

  const view = render(
    <QueryClientProvider client={queryClient}>
      <div>
        <p id={taskTextId(taskId)}>{TASK_TEXT}</p>
        <DashboardTaskActions
          taskId={taskId}
          describedById={taskTextId(taskId)}
        />
      </div>
    </QueryClientProvider>
  );

  const cachedTaskIds = () => {
    const section = queryClient.getQueryData<HomeDashboardResponse>(
      homeDashboardKeys.all
    )?.data.attributes.tasks;
    const rows =
      section?.status === DashboardSectionStatus.READY
        ? section.data?.tasks
        : undefined;
    return (rows ?? []).map(task => task.task_id);
  };

  return { ...view, queryClient, cachedTaskIds };
}

function doneButton() {
  return screen.getByTestId('dashboard-task-action-done');
}

/** Every URL a spied `fetch` was asked for. */
function requestedUrls(): string[] {
  return mockFetch.mock.calls.map(([input]) => String(input));
}

describe('DashboardTaskActions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('the button itself (W24)', () => {
    it('offers exactly one action, and it is Done', () => {
      renderActions();

      const buttons = screen.getAllByRole('button');
      expect(buttons).toHaveLength(1);
      expect(buttons[0]).toHaveTextContent('Done');
    });

    it('is an outline, small button carrying a check icon', () => {
      const { container } = renderActions();

      const button = doneButton();
      expect(button).toHaveAttribute('data-slot', 'button');
      expect(button.className).toMatch(/border/);
      expect(container.querySelector('svg')).toHaveAttribute(
        'aria-hidden',
        'true'
      );
    });

    /**
     * The button's accessible name says what pressing it *does* and contains
     * the visible label, so a user speaking what they see still addresses it
     * (WCAG 2.5.3); the *group* is described by the commitment, because every
     * row's button is named the same thing and a label long enough to identify
     * one would be read out five times over.
     */
    it('is named for what it does, and described by the commitment', () => {
      renderActions();

      expect(doneButton()).toHaveAccessibleName('Mark done');
      const group = screen.getByRole('group', { name: 'Task actions' });
      expect(group).toHaveAttribute('aria-describedby', taskTextId(TASK_ID));
      expect(doneButton().closest('[role="group"]')).toBe(group);
    });

    it('offers no delete, no cancel and no retarget (wireframe gaps 8 and 10)', () => {
      renderActions();

      expect(
        screen.queryByRole('button', { name: /delete/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /cancel/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /reschedule|resurrect|reopen/i })
      ).not.toBeInTheDocument();
    });

    it('never navigates: it is a button, not a link', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      renderActions();

      expect(doneButton().closest('a')).toBeNull();
      expect(doneButton()).toHaveAttribute('type', 'button');

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith('Task marked done');
      });
      expect(window.location.pathname).toBe('/');
    });
  });

  describe('marking the task done', () => {
    it('PATCHes the task to done', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      renderActions();

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });
      const [url, init] = mockFetch.mock.calls[0];
      expect(String(url)).toContain(`/api/tasks/${TASK_ID}`);
      expect((init as RequestInit).method).toBe('PATCH');
      expect(JSON.parse((init as RequestInit).body as string)).toMatchObject({
        data: { attributes: { status: TaskStatus.DONE } },
      });
    });

    it('takes the row out of the section, leaving the others alone', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      const { cachedTaskIds } = renderActions();

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(cachedTaskIds()).toEqual([99]);
      });
    });

    it('puts the row back when the write fails', async () => {
      mockFetch.mockResolvedValue(failureResponse('Something went wrong'));
      const { cachedTaskIds } = renderActions();

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Something went wrong');
      });
      expect(cachedTaskIds()).toEqual([TASK_ID, 99]);
    });

    /**
     * **AC6**, and the client half of ITER18-005 Phase 7's contract: the
     * section updates and the summary refreshes on the *next* load. The
     * dashboard's own read regenerates nothing server-side, so what has to be
     * true here is that ticking a task asks for no summary and posts no
     * regeneration.
     */
    it('requests no summary and regenerates nothing (AC6)', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      renderActions();

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalled();
      });
      expect(
        requestedUrls().filter(url => url.includes('daily-summary'))
      ).toEqual([]);
      expect(requestedUrls().filter(url => url.includes('regenerate'))).toEqual(
        []
      );
    });
  });

  describe('while a write against the task is in flight', () => {
    /** A held-open `fetch`, plus the trigger that finally answers it. */
    function heldRequest(): () => void {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => resolve(okResponse(TaskStatus.DONE));
          })
      );
      return () => release();
    }

    it('disables the button and reports the group busy', async () => {
      const release = heldRequest();
      renderActions();

      await userEvent.click(doneButton());

      await waitFor(() => {
        expect(doneButton()).toBeDisabled();
      });
      // The *group* carries the busy state, not the control that was pressed:
      // the optimistic removal rewrites the section before the request
      // settles, so on a real card the button is gone by the time it does.
      expect(
        screen.getByRole('group', { name: 'Task actions' })
      ).toHaveAttribute('aria-busy', 'true');

      release();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalled();
      });
    });

    it('sends no second request when clicked again mid-write', async () => {
      const release = heldRequest();
      renderActions();

      await userEvent.click(doneButton());
      await waitFor(() => {
        expect(doneButton()).toBeDisabled();
      });
      await userEvent.click(doneButton());

      expect(mockFetch).toHaveBeenCalledTimes(1);

      release();
      await waitFor(() => {
        expect(toast.success).toHaveBeenCalled();
      });
    });
  });

  describe('keyboard', () => {
    it('is reachable by tab and acts on Enter', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      renderActions();

      await userEvent.tab();
      expect(doneButton()).toHaveFocus();

      await userEvent.keyboard('{Enter}');

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });
    });

    it('acts on Space', async () => {
      mockFetch.mockResolvedValue(okResponse(TaskStatus.DONE));
      renderActions();

      await userEvent.tab();
      await userEvent.keyboard('{ }');

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });
    });
  });
});
