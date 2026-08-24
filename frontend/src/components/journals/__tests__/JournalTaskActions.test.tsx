/**
 * @jest-environment jsdom
 */

/**
 * Tests for JournalTaskActions — the inline status actions on a task row.
 *
 * Three things these assert that the phase's acceptance criteria rest on:
 *
 * - **A cancelled task offers no status action.** The service refuses
 *   `cancelled → done` and `cancelled → not done` alike, so either button
 *   could do nothing but draw a 409. Its way out is the retarget dialog.
 * - **Cancel is the ordinary action and delete is the exception**, which is
 *   the specification's stance stated twice ("cancel over delete", and "the UI
 *   should treat cancelling as the normal action and deletion as the
 *   exception"). Delete is last, muted, and gated behind a confirmation.
 * - **The row moves before the response does, and moves back if it fails.**
 *   The optimistic patch lives in `useUpdateTask`; these tests drive it through
 *   the button the user actually presses.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { JournalTaskActions } from '../JournalTaskActions';
import { JournalTasksSection } from '../JournalTasksSection';
import { createMockJournalTask, createTestQueryClient } from '../test-helpers';
import { taskKeys } from '@/lib/api/tasks';
import {
  TaskLinkRole,
  TaskStatus,
  type JournalTasksResponse,
} from '@/types/tasks';
import type { JournalTaskResource } from '@/types/tasks';

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

const TEXT_ID = 'task-text-1';
const JOURNAL_ID = '7';

/** A 200 carrying the write shape the PATCH answers with. */
function okResponse(status: TaskStatus): Response {
  return {
    ok: true,
    status: 200,
    json: jest.fn().mockResolvedValue({
      data: { type: 'tasks', id: '1', attributes: { status } },
    }),
  } as unknown as Response;
}

/** A 204, as the DELETE answers. */
function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: jest.fn().mockRejectedValue(new SyntaxError('no body')),
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

/** The journal listing the row was rendered from, as the cache holds it. */
function cachedListing(task: JournalTaskResource): JournalTasksResponse {
  return {
    data: [task],
    meta: { groups: { due: [Number(task.id)], created: [], mentioned: [] } },
  };
}

/**
 * Render the actions beside the text they act on, as the row mounts them.
 *
 * The listing is seeded into the cache so the optimistic patch and its
 * rollback have something real to move, rather than being asserted on a cache
 * nothing reads.
 */
function renderActions(
  task = createMockJournalTask(),
  role: TaskLinkRole = TaskLinkRole.DUE
) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(
    taskKeys.journalList(JOURNAL_ID),
    cachedListing(task)
  );

  const view = render(
    <QueryClientProvider client={queryClient}>
      <div>
        <p id={TEXT_ID}>{task.attributes.text}</p>
        <JournalTaskActions
          task={task}
          journalId={JOURNAL_ID}
          role={role}
          describedById={TEXT_ID}
        />
      </div>
    </QueryClientProvider>
  );

  const cachedStatus = () =>
    queryClient.getQueryData<JournalTasksResponse>(
      taskKeys.journalList(JOURNAL_ID)
    )?.data[0]?.attributes.status;

  return { ...view, queryClient, cachedStatus };
}

/** The request body a spied `fetch` was called with. */
function requestBody(call = 0): unknown {
  const init = mockFetch.mock.calls[call][1] as RequestInit;
  return JSON.parse(init.body as string);
}

function actionGroup(): HTMLElement {
  return screen.getByRole('group', { name: 'Task actions' });
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('JournalTaskActions', () => {
  describe('what each status offers', () => {
    it('offers a not-done task completion and cancellation', () => {
      renderActions(createMockJournalTask({ status: TaskStatus.NOT_DONE }));

      expect(
        screen.getByRole('button', { name: 'Mark done' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Return to not done' })
      ).not.toBeInTheDocument();
    });

    it('offers a done task the way back and cancellation', () => {
      renderActions(createMockJournalTask({ status: TaskStatus.DONE }));

      expect(
        screen.getByRole('button', { name: 'Return to not done' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Mark done' })
      ).not.toBeInTheDocument();
    });

    /**
     * The refusal this asserts is the whole reason the offer table exists:
     * a cancelled task is left only by retargeting, so a status button here
     * could do nothing but draw a 409.
     */
    it('offers a cancelled task no status action at all', () => {
      renderActions(createMockJournalTask({ status: TaskStatus.CANCELLED }));

      expect(
        screen.queryByRole('button', { name: 'Mark done' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Return to not done' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Cancel task' })
      ).not.toBeInTheDocument();
    });

    it('still offers a lapsed task completion and cancellation', () => {
      renderActions(
        createMockJournalTask({ status: TaskStatus.NOT_DONE, lapsed: true })
      );

      expect(
        screen.getByRole('button', { name: 'Mark done' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toBeInTheDocument();
    });
  });

  describe('happy paths', () => {
    it.each([
      ['Mark done', TaskStatus.NOT_DONE, TaskStatus.DONE],
      ['Return to not done', TaskStatus.DONE, TaskStatus.NOT_DONE],
      ['Cancel task', TaskStatus.NOT_DONE, TaskStatus.CANCELLED],
    ])('%s patches the task to %s', async (name, from, to) => {
      mockFetch.mockResolvedValueOnce(okResponse(to));
      renderActions(createMockJournalTask({ status: from }));

      await userEvent.click(screen.getByRole('button', { name }));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/tasks/1',
          expect.objectContaining({ method: 'PATCH' })
        );
      });
      expect(requestBody()).toEqual({
        data: { type: 'tasks', id: '1', attributes: { status: to } },
      });
    });

    it('shows the new status before the request is answered', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      const { cachedStatus } = renderActions();

      await userEvent.click(screen.getByRole('button', { name: 'Mark done' }));

      await waitFor(() => {
        expect(cachedStatus()).toBe(TaskStatus.DONE);
      });
      release();
    });

    it('never navigates away', async () => {
      mockFetch.mockResolvedValueOnce(okResponse(TaskStatus.DONE));
      renderActions();

      await userEvent.click(screen.getByRole('button', { name: 'Mark done' }));

      expect(within(actionGroup()).queryByRole('link')).not.toBeInTheDocument();
    });
  });

  describe('failure rollback', () => {
    it.each([
      ['Mark done', TaskStatus.NOT_DONE],
      ['Return to not done', TaskStatus.DONE],
      ['Cancel task', TaskStatus.NOT_DONE],
    ])(
      '%s leaves the row as it was when the write fails',
      async (name, from) => {
        mockFetch.mockResolvedValueOnce(failureResponse('The server said no'));
        const { cachedStatus } = renderActions(
          createMockJournalTask({ status: from })
        );

        await userEvent.click(screen.getByRole('button', { name }));

        await waitFor(() => {
          expect(toast.error).toHaveBeenCalledWith('The server said no');
        });
        expect(cachedStatus()).toBe(from);
      }
    );
  });

  describe('while a write is in flight', () => {
    it('disables every action and marks the group busy', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderActions();

      const done = screen.getByRole('button', { name: 'Mark done' });
      await userEvent.click(done);

      await waitFor(() => {
        expect(done).toBeDisabled();
      });
      expect(actionGroup()).toHaveAttribute('aria-busy', 'true');
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toBeDisabled();
      expect(
        screen.getByRole('button', { name: 'Delete task' })
      ).toBeDisabled();

      release();
      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: 'Cancel task' })
        ).toBeEnabled();
      });
    });

    it('leaves every action enabled and the group unbusy at rest', () => {
      renderActions();

      expect(screen.getByRole('button', { name: 'Mark done' })).toBeEnabled();
      expect(actionGroup()).toHaveAttribute('aria-busy', 'false');
    });
  });

  /**
   * A task holding two roles in one journal is rendered **once per group** —
   * the grouping contract Phase 16 pins with its own test — so the same task
   * has two independent `JournalTaskActions`, each with its own mutation
   * state. A guard that only knows about its own instance leaves the twin
   * live: the optimistic patch rerenders it offering the opposite move, and a
   * second click races the first write. Which one the server ends up keeping
   * is then decided by request ordering.
   */
  describe('a task rendered under two groups', () => {
    function renderTwice(task = createMockJournalTask()) {
      const queryClient = createTestQueryClient();
      queryClient.setQueryData(
        taskKeys.journalList(JOURNAL_ID),
        cachedListing(task)
      );

      return render(
        <QueryClientProvider client={queryClient}>
          <div>
            <p id={TEXT_ID}>{task.attributes.text}</p>
            <div data-testid='copy-created'>
              <JournalTaskActions
                task={task}
                journalId={JOURNAL_ID}
                role={TaskLinkRole.CREATED}
                describedById={TEXT_ID}
              />
            </div>
            <div data-testid='copy-mentioned'>
              <JournalTaskActions
                task={task}
                journalId={JOURNAL_ID}
                role={TaskLinkRole.MENTIONED}
                describedById={TEXT_ID}
              />
            </div>
          </div>
        </QueryClientProvider>
      );
    }

    it('locks the twin copy while either copy is writing', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderTwice();

      const created = within(screen.getByTestId('copy-created'));
      const mentioned = within(screen.getByTestId('copy-mentioned'));

      await userEvent.click(created.getByRole('button', { name: 'Mark done' }));

      await waitFor(() => {
        expect(
          mentioned.getByRole('button', { name: 'Mark done' })
        ).toBeDisabled();
      });
      expect(
        mentioned.getByRole('button', { name: 'Cancel task' })
      ).toBeDisabled();
      expect(
        mentioned.getByRole('button', { name: 'Delete task' })
      ).toBeDisabled();
      // The retarget dialog is a write against the same task, so a twin that
      // could open one mid-write would queue exactly the race the guard exists
      // to prevent.
      expect(
        mentioned.getByTestId('journal-task-action-retarget')
      ).toBeDisabled();

      release();
      await waitFor(() => {
        expect(
          mentioned.getByRole('button', { name: 'Mark done' })
        ).toBeEnabled();
      });
    });

    it('marks both copies busy, not just the clicked one', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderTwice();

      const created = within(screen.getByTestId('copy-created'));
      const mentioned = within(screen.getByTestId('copy-mentioned'));

      await userEvent.click(created.getByRole('button', { name: 'Mark done' }));

      await waitFor(() => {
        expect(
          mentioned.getByRole('group', { name: 'Task actions' })
        ).toHaveAttribute('aria-busy', 'true');
      });

      release();
    });

    it('sends only one request when the twin is clicked during a write', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderTwice();

      const created = within(screen.getByTestId('copy-created'));
      const mentioned = within(screen.getByTestId('copy-mentioned'));

      await userEvent.click(created.getByRole('button', { name: 'Mark done' }));
      await waitFor(() => {
        expect(
          mentioned.getByRole('button', { name: 'Cancel task' })
        ).toBeDisabled();
      });
      await userEvent.click(
        mentioned.getByRole('button', { name: 'Cancel task' })
      );

      expect(mockFetch).toHaveBeenCalledTimes(1);

      release();
    });
  });

  /**
   * Mounted the way the app mounts it, against live query data.
   *
   * Every other test here passes a **static** `task` prop, which cannot see
   * what the optimistic patch does to the row: in the real section the patch
   * rewrites the cached status, the listing's observer rerenders, and the row
   * comes back offering the *new* status's actions — so the button that was
   * clicked no longer exists by the time the request settles. A busy signal
   * pinned to "the action whose target matches the pending write" is therefore
   * false on everything the user can still see.
   */
  describe('mounted against the listing it really reads', () => {
    function renderSection(task = createMockJournalTask()) {
      const queryClient = createTestQueryClient();
      queryClient.setQueryData(
        taskKeys.journalList(JOURNAL_ID),
        cachedListing(task)
      );

      return render(
        <QueryClientProvider client={queryClient}>
          <JournalTasksSection journalId={JOURNAL_ID} />
        </QueryClientProvider>
      );
    }

    it('reports the group busy while the write is in flight', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderSection();

      await userEvent.click(screen.getByRole('button', { name: 'Mark done' }));

      // The optimistic patch has already flipped the row, so the control that
      // was clicked is gone and the way back is what is on screen.
      await waitFor(() => {
        expect(
          screen.getByRole('button', { name: 'Return to not done' })
        ).toBeInTheDocument();
      });

      const group = screen.getByRole('group', { name: 'Task actions' });
      expect(group).toHaveAttribute('aria-busy', 'true');
      expect(
        screen.getByRole('button', { name: 'Return to not done' })
      ).toBeDisabled();

      release();
      await waitFor(() => {
        expect(group).toHaveAttribute('aria-busy', 'false');
      });
    });

    it('leaves the group unbusy at rest', () => {
      renderSection();

      expect(
        screen.getByRole('group', { name: 'Task actions' })
      ).toHaveAttribute('aria-busy', 'false');
    });
  });

  describe('keyboard operation', () => {
    it('reaches every action by tabbing, in the order they are shown', async () => {
      renderActions();

      const expected = [
        'Mark done',
        'Cancel task',
        'Reschedule task onto a new due journal',
        'Delete task',
      ];
      for (const name of expected) {
        await userEvent.tab();
        expect(screen.getByRole('button', { name })).toHaveFocus();
      }
    });

    it.each([['{Enter}'], [' ']])('activates with %s', async key => {
      mockFetch.mockResolvedValueOnce(okResponse(TaskStatus.DONE));
      renderActions();

      screen.getByRole('button', { name: 'Mark done' }).focus();
      await userEvent.keyboard(key);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe('accessible naming', () => {
    it('names each action for what pressing it does', () => {
      renderActions();

      expect(
        screen.getByRole('button', { name: 'Mark done' })
      ).toHaveTextContent('Done');
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toHaveTextContent('Cancel');
    });

    /**
     * Two rows carry identically-named buttons, so the group is described by
     * the task text and a screen reader says which commitment it is about.
     */
    it('describes the action group by the task it acts on', () => {
      renderActions();

      expect(actionGroup()).toHaveAttribute('aria-describedby', TEXT_ID);
    });
  });

  describe('delete is the exception, not the ordinary action', () => {
    it('places delete last, after cancel', () => {
      renderActions();

      const names = within(actionGroup())
        .getAllByRole('button')
        .map(button => button.getAttribute('aria-label'));

      expect(names).toEqual([
        'Mark done',
        'Cancel task',
        'Reschedule task onto a new due journal',
        'Delete task',
      ]);
    });

    it('presents delete quietly rather than as a destructive button', () => {
      renderActions();

      const remove = screen.getByRole('button', { name: 'Delete task' });
      expect(remove.className).toContain('text-muted-foreground');
      expect(remove.className).not.toContain('bg-destructive');
    });

    it('asks before deleting rather than deleting on the click', async () => {
      renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );

      expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('says that cancelling keeps the task, so the choice is informed', async () => {
      renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );

      const dialog = await screen.findByRole('alertdialog');
      expect(within(dialog).getByText(/cancel/i)).toBeInTheDocument();
    });

    it('deletes once the confirmation is given', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );
      const dialog = await screen.findByRole('alertdialog');
      await userEvent.click(
        within(dialog).getByRole('button', { name: 'Delete' })
      );

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          '/api/tasks/1',
          expect.objectContaining({ method: 'DELETE' })
        );
      });
    });

    it('reports a failed delete rather than leaving the row looking gone', async () => {
      mockFetch.mockResolvedValueOnce(failureResponse('Could not delete it'));
      const { cachedStatus } = renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );
      const dialog = await screen.findByRole('alertdialog');
      await userEvent.click(
        within(dialog).getByRole('button', { name: 'Delete' })
      );

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Could not delete it');
      });
      expect(cachedStatus()).toBe(TaskStatus.NOT_DONE);
    });

    it('sends nothing when the confirmation is declined', async () => {
      renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );
      const dialog = await screen.findByRole('alertdialog');
      await userEvent.click(
        within(dialog).getByRole('button', { name: 'Keep task' })
      );

      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('the confirmation dialog manages focus', () => {
    it('moves focus into the dialog when it opens', async () => {
      renderActions();

      await userEvent.click(
        screen.getByRole('button', { name: 'Delete task' })
      );

      const dialog = await screen.findByRole('alertdialog');
      await waitFor(() => {
        expect(dialog).toContainElement(
          document.activeElement as HTMLElement | null
        );
      });
    });

    it('closes on Escape and gives focus back to the control that opened it', async () => {
      renderActions();

      const trigger = screen.getByRole('button', { name: 'Delete task' });
      await userEvent.click(trigger);
      await screen.findByRole('alertdialog');

      await userEvent.keyboard('{Escape}');

      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
      expect(trigger).toHaveFocus();
    });
  });
  /**
   * The way out of every status, and the *only* way out of cancelled.
   *
   * The dialog itself is tested in `RetargetTaskDialog.test.tsx`; what belongs
   * here is that the row offers it at all, where it sits among the actions
   * beside it, and that it locks with them.
   */
  describe('the retarget affordance', () => {
    it.each([
      [TaskStatus.NOT_DONE, /reschedule/i],
      [TaskStatus.DONE, /reopen/i],
      [TaskStatus.CANCELLED, /resurrect/i],
    ])('offers a %s task a way onto a new due journal', (status, name) => {
      renderActions(createMockJournalTask({ status }));

      expect(
        screen.getByTestId('journal-task-action-retarget')
      ).toHaveAccessibleName(name);
    });

    /**
     * The specification's list for a lapsed task is resurrect, cancel and
     * done. The other two are Phase 17's; this asserts all three together,
     * because "expose them inline" is a claim about the row rather than about
     * any one control.
     */
    it('gives a lapsed row all three of resurrect, cancel and done', () => {
      renderActions(
        createMockJournalTask({ status: TaskStatus.NOT_DONE, lapsed: true })
      );

      expect(
        screen.getByTestId('journal-task-action-retarget')
      ).toHaveAccessibleName(/resurrect/i);
      expect(
        screen.getByRole('button', { name: 'Mark done' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Cancel task' })
      ).toBeInTheDocument();
    });

    it('sits after the status actions and before the delete', () => {
      renderActions(createMockJournalTask({ status: TaskStatus.NOT_DONE }));

      const order = within(actionGroup())
        .getAllByRole('button')
        .map(button => button.getAttribute('data-testid'));

      expect(order).toEqual([
        'journal-task-action-done',
        'journal-task-action-cancel',
        'journal-task-action-retarget',
        'journal-task-action-delete',
      ]);
    });

    /**
     * Not `destructive`, and not a link: retargeting is an ordinary move, and
     * the row never navigates away from the journal being read.
     */
    it('is an ordinary action rather than a destructive one', () => {
      renderActions();

      const trigger = screen.getByTestId('journal-task-action-retarget');
      expect(trigger.className).not.toMatch(/bg-destructive/);
      expect(trigger.tagName).toBe('BUTTON');
      expect(trigger).not.toHaveAttribute('href');
    });

    it('opens no request of its own until the dialog is submitted', async () => {
      renderActions();

      await userEvent.click(screen.getByTestId('journal-task-action-retarget'));
      await screen.findByRole('dialog');

      const wrote = mockFetch.mock.calls.filter(([, init]) =>
        ['POST', 'PATCH', 'DELETE'].includes(
          String((init as RequestInit | undefined)?.method ?? 'GET')
        )
      );
      expect(wrote).toEqual([]);
    });

    it('is locked while a write against the task is in flight', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderActions();

      await userEvent.click(screen.getByRole('button', { name: 'Mark done' }));

      await waitFor(() => {
        expect(
          screen.getByTestId('journal-task-action-retarget')
        ).toBeDisabled();
      });

      release();
      await waitFor(() => {
        expect(
          screen.getByTestId('journal-task-action-retarget')
        ).toBeEnabled();
      });
    });
  });

  /**
   * Criterion 2: "a mention link can be **removed** from the journal that
   * carries it; creating and due links offer no remove affordance."
   *
   * The affordance belongs to the row's **group**, not to the task. A journal
   * renders a task holding two roles once per group, so the same commitment
   * can show a remove under *Mentioned* and none under *Due* — which is why
   * these actions take a role rather than deriving one from `link_roles`.
   */
  describe('removing a mention', () => {
    const REMOVE = 'Remove mention from this journal';

    it.each([TaskLinkRole.DUE, TaskLinkRole.CREATED])(
      'offers no remove on a %s row',
      role => {
        renderActions(createMockJournalTask(), role);

        expect(
          screen.queryByRole('button', { name: REMOVE })
        ).not.toBeInTheDocument();
        expect(
          screen.queryByTestId('journal-task-action-detach')
        ).not.toBeInTheDocument();
      }
    );

    it('offers a remove on a mentioned row', () => {
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      expect(screen.getByRole('button', { name: REMOVE })).toBeInTheDocument();
    });

    /**
     * Every status keeps the affordance. A mention is a statement that the
     * task was discussed here, and a cancelled or done task's mentions are as
     * removable as a live one's — the service reads the link, not the status.
     */
    it.each([TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED])(
      'offers it on a %s task too',
      status => {
        renderActions(
          createMockJournalTask({ status }),
          TaskLinkRole.MENTIONED
        );

        expect(
          screen.getByRole('button', { name: REMOVE })
        ).toBeInTheDocument();
      }
    );

    it('detaches this journal from the task, and nothing else', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      await userEvent.click(screen.getByRole('button', { name: REMOVE }));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          `/api/tasks/1/relationships/intermediate-journals/${JOURNAL_ID}`,
          { method: 'DELETE', credentials: 'include' }
        );
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(toast.success).toHaveBeenCalledWith(
        'Journal unlinked successfully'
      );
    });

    /**
     * Removing a mention is reversible by the affordance in the same card, so
     * it is not gated behind a confirmation the way deletion is — but it is
     * still not an *ordinary* action, so it is presented as quietly as delete
     * and stays out of the destructive variant.
     */
    it('removes on the click rather than asking first', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      await userEvent.click(screen.getByRole('button', { name: REMOVE }));

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    });

    it('is presented quietly and never as a destructive button', () => {
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      const remove = screen.getByRole('button', { name: REMOVE });
      expect(remove.className).toContain('text-muted-foreground');
      expect(remove.className).not.toContain('bg-destructive');
    });

    it('sits after the retarget and before the delete, which stays last', () => {
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      const order = within(actionGroup())
        .getAllByRole('button')
        .map(button => button.getAttribute('data-testid'));

      expect(order).toEqual([
        'journal-task-action-done',
        'journal-task-action-cancel',
        'journal-task-action-retarget',
        'journal-task-action-detach',
        'journal-task-action-delete',
      ]);
    });

    it('is locked while a write against the task is in flight', async () => {
      let release: () => void = () => undefined;
      mockFetch.mockImplementationOnce(
        () =>
          new Promise<Response>(resolve => {
            release = () => {
              resolve(okResponse(TaskStatus.DONE));
            };
          })
      );
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      await userEvent.click(screen.getByRole('button', { name: 'Mark done' }));

      await waitFor(() => {
        expect(screen.getByRole('button', { name: REMOVE })).toBeDisabled();
      });

      release();
      await waitFor(() => {
        expect(screen.getByRole('button', { name: REMOVE })).toBeEnabled();
      });
    });

    /**
     * The row does not leave the listing until the invalidated refetch comes
     * back, a round trip after the `DELETE` resolves, and the shared in-flight
     * guard goes false the moment it does. The second press would be refused
     * on exactly the shape this affordance exists for — a journal that is also
     * an anchor keeps its intermediate link removable, and the service raises
     * rather than answering idempotently the second time — so the user would
     * see "Journal unlinked successfully" followed by an error naming the
     * anchor, reading as though the removal had failed.
     */
    it('stays locked after the removal settles, not only while it is in flight', async () => {
      mockFetch.mockResolvedValueOnce(noContentResponse());
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      await userEvent.click(screen.getByRole('button', { name: REMOVE }));

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalled();
      });
      expect(screen.getByRole('button', { name: REMOVE })).toBeDisabled();
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('reports a failed removal rather than leaving the row looking unlinked', async () => {
      mockFetch.mockResolvedValueOnce(failureResponse('Journal is not linked'));
      renderActions(createMockJournalTask(), TaskLinkRole.MENTIONED);

      await userEvent.click(screen.getByRole('button', { name: REMOVE }));

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Journal is not linked');
      });
      // Still there *and* still pressable: a failure leaves the link in place,
      // so the way to try again must not have been locked away with it.
      expect(screen.getByRole('button', { name: REMOVE })).toBeEnabled();
    });
  });
});
