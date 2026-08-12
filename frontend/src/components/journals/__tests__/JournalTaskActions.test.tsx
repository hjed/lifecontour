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
import { createMockJournalTask, createTestQueryClient } from '../test-helpers';
import { taskKeys } from '@/lib/api/tasks';
import { TaskStatus, type JournalTasksResponse } from '@/types/tasks';
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
function renderActions(task = createMockJournalTask()) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(
    taskKeys.journalList(JOURNAL_ID),
    cachedListing(task)
  );

  const view = render(
    <QueryClientProvider client={queryClient}>
      <div>
        <p id={TEXT_ID}>{task.attributes.text}</p>
        <JournalTaskActions task={task} describedById={TEXT_ID} />
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
    it('disables every action and marks the acting one busy', async () => {
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
      expect(done).toHaveAttribute('aria-busy', 'true');
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

    it('leaves every action enabled and unbusy at rest', () => {
      renderActions();

      const done = screen.getByRole('button', { name: 'Mark done' });
      expect(done).toBeEnabled();
      expect(done).toHaveAttribute('aria-busy', 'false');
    });
  });

  describe('keyboard operation', () => {
    it('reaches every action by tabbing, in the order they are shown', async () => {
      renderActions();

      const expected = ['Mark done', 'Cancel task', 'Delete task'];
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

      expect(names).toEqual(['Mark done', 'Cancel task', 'Delete task']);
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
});
