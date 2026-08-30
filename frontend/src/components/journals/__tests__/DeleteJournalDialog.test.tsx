/**
 * @jest-environment jsdom
 */

/**
 * Tests for the journal delete confirmation and its refusal.
 *
 * A journal that anchors a task cannot be deleted, whatever the task's status,
 * and the specification asks that the refusal be *explanatory, not opaque*:
 * every blocking task named, and each one linked to a journal where it can be
 * actioned. The backend already answers that way — a 409
 * `JOURNAL_HAS_ANCHORED_TASKS` carrying `meta.blocking_tasks` — so what is
 * asserted here is that the dialog turns that payload into something a user
 * can act on without leaving the page they are on.
 *
 * Nothing is mocked below the component: the delete goes through `fetch`, so
 * these tests exercise the real narrowing in `blockingTasksFrom` rather than a
 * hook standing in for it. The one exception is the router, which has no
 * jsdom implementation to exercise.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { DeleteJournalDialog } from '../DeleteJournalDialog';
import { createMockJournal, createTestQueryClient } from '../test-helpers';
import { SUCCESS_MESSAGES } from '@/lib/constants';
import { JournalType, type Journal } from '@/types/journals';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` mocks `@/lib/constants` down to the endpoints the auth tests
// need, which would leave `API_ENDPOINTS.JOURNALS` undefined.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const JOURNAL_ID = 10;

/** The journal under the delete button, event-typed unless told otherwise. */
function journalFixture(types: JournalType[] = [JournalType.EVENT]): Journal {
  const { attributes } = createMockJournal({
    title: 'Site visit',
    types,
  });
  return { ...attributes, id: String(JOURNAL_ID) };
}

interface BlockerOverrides {
  task_id?: number;
  text?: string;
  status?: string;
  blocking_roles?: string[];
  action_journal_id?: number;
  action_journal_title?: string;
}

function blocker(overrides: BlockerOverrides = {}) {
  return {
    task_id: 7,
    text: 'print the permit',
    status: 'not_done',
    blocking_roles: ['due'],
    action_journal_id: 20,
    action_journal_title: 'Monday Planning',
    ...overrides,
  };
}

/** The 409 the delete guard answers with, shaped as the route really sends it. */
function refusal(...blockers: ReturnType<typeof blocker>[]) {
  return {
    ok: false,
    status: 409,
    json: async () => ({
      errors: [
        {
          id: 'e1',
          status: '409',
          code: 'JOURNAL_HAS_ANCHORED_TASKS',
          title: 'Conflict',
          detail: 'This journal cannot be deleted because tasks anchor to it.',
          meta: { journal_id: JOURNAL_ID, blocking_tasks: blockers },
        },
      ],
    }),
  } as Response;
}

const deleted = () => ({ ok: true, json: async () => ({}) }) as Response;

function renderDialog(journal: Journal = journalFixture()) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <DeleteJournalDialog journal={journal} />
    </QueryClientProvider>
  );
}

/** Open the dialog and press the destructive confirm. */
async function confirmDelete(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Delete journal' }));
  await user.click(await screen.findByTestId('confirm-delete-journal'));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockFetch.mockReset();
});

describe('DeleteJournalDialog', () => {
  describe('the confirmation step', () => {
    it('asks before deleting anything', async () => {
      const user = userEvent.setup();
      renderDialog();

      expect(mockFetch).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: 'Delete journal' }));

      expect(
        await screen.findByRole('alertdialog', { name: /delete this journal/i })
      ).toBeInTheDocument();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('steers an event journal toward cancelling it instead', async () => {
      const user = userEvent.setup();
      renderDialog(journalFixture([JournalType.EVENT]));

      await user.click(screen.getByRole('button', { name: 'Delete journal' }));

      const steer = await screen.findByTestId('delete-journal-steer');
      // The control is named, because "cancel it instead" is only actionable
      // if the user knows where the cancelled state lives.
      expect(steer).toHaveTextContent(/event status/i);
      expect(steer).toHaveTextContent(/cancelled/i);
    });

    it('tells a journal with no event type that it has no cancelled state', async () => {
      const user = userEvent.setup();
      renderDialog(journalFixture([JournalType.NOTE]));

      await user.click(screen.getByRole('button', { name: 'Delete journal' }));

      const steer = await screen.findByTestId('delete-journal-steer');
      expect(steer).toHaveTextContent(/no cancelled state/i);
      expect(steer).not.toHaveTextContent(/event status/i);
    });

    it('leaves the journal alone when the confirmation is declined', async () => {
      const user = userEvent.setup();
      renderDialog();

      await user.click(screen.getByRole('button', { name: 'Delete journal' }));
      await user.click(await screen.findByRole('button', { name: /keep/i }));

      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('a delete that succeeds', () => {
    it('deletes, reports it and returns to the listing', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(deleted());
      renderDialog();

      await confirmDelete(user);

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/journals');
      });
      expect(mockFetch).toHaveBeenCalledWith(
        `/api/journals/${JOURNAL_ID}`,
        expect.objectContaining({ method: 'DELETE' })
      );
      expect(toast.success).toHaveBeenCalledWith(
        SUCCESS_MESSAGES.JOURNAL_DELETED
      );
      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
    });
  });

  describe('a delete the anchored tasks refuse', () => {
    it('holds the dialog open and names the blocking task', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);

      const row = await screen.findByTestId('journal-delete-blocker-7');
      expect(row).toHaveTextContent('print the permit');
      // Still open: the explanation is a set of links to follow, and a toast
      // would take them away before they could be.
      expect(screen.getByRole('alertdialog')).toBeInTheDocument();
      expect(toast.error).not.toHaveBeenCalled();
      expect(mockPush).not.toHaveBeenCalled();
    });

    it('links each blocker to the journal it can be actioned from', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);

      const link = await screen.findByTestId('journal-delete-blocker-link-7');
      expect(link).toHaveAttribute('href', '/journals/20');
      expect(link).toHaveTextContent('Monday Planning');
    });

    it('does not offer a status change as a way out', async () => {
      // The deletion is refused *whatever* the task's status — this guard's
      // first rule, and the `still refuses once the task is cancelled` e2e
      // proves it. Telling the user to complete or cancel the task would send
      // them through two actions that cannot succeed.
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);

      const dialog = await screen.findByRole('alertdialog');
      expect(dialog).toHaveTextContent(/will not release the journal/i);
      expect(dialog).not.toHaveTextContent(/complete, cancel or retarget/i);
    });

    it('offers the remedy that matches the anchor a task blocks in', async () => {
      // Only two things release an anchor. A retarget moves the *due* one; a
      // creating anchor cannot be moved at all — no service method other than
      // `create_task` accepts one — so deleting the task is the only way out.
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(
        refusal(
          blocker({ task_id: 7, blocking_roles: ['due'] }),
          blocker({
            task_id: 8,
            text: 'book the ferry',
            blocking_roles: ['creating'],
          }),
          blocker({
            task_id: 9,
            text: 'pack the ropes',
            blocking_roles: ['creating', 'due'],
          })
        )
      );
      renderDialog();

      await confirmDelete(user);

      expect(
        await screen.findByTestId('journal-delete-blocker-7')
      ).toHaveTextContent(/retarget it onto another journal/i);

      // Holding the creating anchor is what decides it, with or without the
      // due one: a retarget would move the due anchor and leave this blocked.
      for (const taskId of [8, 9]) {
        const row = screen.getByTestId(`journal-delete-blocker-${taskId}`);
        expect(row).toHaveTextContent(/can’t be changed/i);
        expect(row).toHaveTextContent(/only deleting the task/i);
        expect(row).not.toHaveTextContent(/retarget/i);
      }
    });

    it('offers to stay put when the task is actionable on this journal', async () => {
      // A task created *and* due here is anchored to this journal twice, so
      // the only journal left to send the user to is the one they are on. A
      // link would target the current route, change nothing, and leave the
      // dialog covering the very controls it points at.
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(
        refusal(
          blocker({
            blocking_roles: ['creating', 'due'],
            action_journal_id: JOURNAL_ID,
            action_journal_title: 'Site visit',
          })
        )
      );
      renderDialog();

      await confirmDelete(user);

      const action = await screen.findByTestId('journal-delete-blocker-link-7');
      expect(action).not.toHaveAttribute('href');

      await user.click(action);

      // Closing *is* the navigation here: the task's own controls are on the
      // page underneath.
      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
      expect(mockPush).not.toHaveBeenCalled();
    });

    it('closes as it leaves, so no overlay outlives the page it was on', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);
      await user.click(
        await screen.findByTestId('journal-delete-blocker-link-7')
      );

      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
    });

    it('says why each task blocks, including one holding both anchors', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(
        refusal(
          blocker({ task_id: 7, blocking_roles: ['due'] }),
          blocker({
            task_id: 8,
            text: 'book the ferry',
            blocking_roles: ['creating'],
          }),
          blocker({
            task_id: 9,
            text: 'pack the ropes',
            blocking_roles: ['creating', 'due'],
          })
        )
      );
      renderDialog();

      await confirmDelete(user);

      expect(
        await screen.findByTestId('journal-delete-blocker-7')
      ).toHaveTextContent(/due in this journal/i);
      expect(screen.getByTestId('journal-delete-blocker-8')).toHaveTextContent(
        /created in this journal/i
      );
      const both = screen.getByTestId('journal-delete-blocker-9');
      expect(both).toHaveTextContent(/created in/i);
      expect(both).toHaveTextContent(/due in/i);
    });

    it('names every blocker when there are several', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(
        refusal(
          blocker({ task_id: 7 }),
          blocker({
            task_id: 8,
            text: 'book the ferry',
            action_journal_id: 21,
            action_journal_title: 'Trip prep',
          }),
          blocker({
            task_id: 9,
            text: 'pack the ropes',
            action_journal_id: 22,
            action_journal_title: 'Kit check',
          })
        )
      );
      renderDialog();

      await confirmDelete(user);

      const list = await screen.findByTestId('journal-delete-blockers');
      expect(within(list).getAllByRole('listitem')).toHaveLength(3);
      for (const [taskId, journalId, title] of [
        [7, 20, 'Monday Planning'],
        [8, 21, 'Trip prep'],
        [9, 22, 'Kit check'],
      ] as const) {
        expect(
          within(list).getByTestId(`journal-delete-blocker-link-${taskId}`)
        ).toHaveAttribute('href', `/journals/${journalId}`);
        expect(
          within(list).getByTestId(`journal-delete-blocker-link-${taskId}`)
        ).toHaveTextContent(title);
      }
    });

    it('shows a blocker’s status, so a done task does not read as an oversight', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(
        refusal(blocker({ status: 'done', blocking_roles: ['creating'] }))
      );
      renderDialog();

      await confirmDelete(user);

      expect(
        await screen.findByTestId('journal-delete-blocker-7')
      ).toHaveTextContent(/done/i);
    });

    it('keeps steering toward cancelling the journal instead', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);

      expect(
        await screen.findByTestId('delete-journal-steer')
      ).toHaveTextContent(/event status/i);
    });

    it('retries the delete in place once the blockers are cleared', async () => {
      const user = userEvent.setup();
      mockFetch
        .mockResolvedValueOnce(refusal(blocker()))
        .mockResolvedValueOnce(deleted());
      renderDialog();

      await confirmDelete(user);
      await user.click(await screen.findByTestId('retry-delete-journal'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/journals');
      });
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('forgets the blockers when the dialog is closed and reopened', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce(refusal(blocker()));
      renderDialog();

      await confirmDelete(user);
      await screen.findByTestId('journal-delete-blocker-7');

      await user.click(screen.getByRole('button', { name: /close/i }));
      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Delete journal' }));

      expect(await screen.findByTestId('confirm-delete-journal')).toBeVisible();
      expect(
        screen.queryByTestId('journal-delete-blocker-7')
      ).not.toBeInTheDocument();
    });
  });

  describe('a failure that is not the anchored-tasks refusal', () => {
    it('is reported the ordinary way and closes the dialog', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({
          errors: [{ status: '500', detail: 'Something broke' }],
        }),
      } as Response);
      renderDialog();

      await confirmDelete(user);

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Something broke');
      });
      await waitFor(() => {
        expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      });
      expect(mockPush).not.toHaveBeenCalled();
    });
  });
});
