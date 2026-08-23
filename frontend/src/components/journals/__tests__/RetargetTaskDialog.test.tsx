/**
 * @jest-environment jsdom
 */

/**
 * Tests for the retarget and resurrect dialog.
 *
 * This is the one surface that does four different things through one call:
 * it extends a deadline, brings a **lapsed** commitment back, brings a
 * **cancelled** one back — its only exit, since the service refuses both
 * status calls out of cancelled — and reopens a **done** task, which the
 * specification says the UI must warn about *before* it happens.
 *
 * Nothing is mocked below the component. The picker's listing, the user's
 * timezone and the retarget itself all go through `fetch`, so what is asserted
 * is the request the user's clicks actually produce and the cache they leave
 * behind, not a hook standing in for them.
 *
 * The confirmation is **the server's refusal**, not a client-side prediction.
 * A done task's retarget is sent without the acknowledgement, refused with
 * `TASK_REOPEN_NOT_ACKNOWLEDGED` — which writes nothing, and which
 * `useRetargetTask` deliberately does not toast — and only then confirmed and
 * re-sent. Predicting it in the browser would be a second copy of the
 * service's rule, and it would ask the user to confirm requests that were
 * never going to succeed, since the future-date check runs first.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { RetargetTaskDialog } from '../RetargetTaskDialog';
import {
  createMockJournalTask,
  createMockTaskJournalRef,
  createTestQueryClient,
} from '../test-helpers';
import { addDaysToIsoDate, todayIn } from '@/lib/future-journals';
import { SUCCESS_MESSAGES } from '@/lib/constants';
import { JournalType } from '@/types/journals';
import { LapseReason, TaskStatus } from '@/types/tasks';
import type { JournalTaskResource } from '@/types/tasks';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` mocks `@/lib/constants` down to the endpoints the auth tests
// need, which would leave `API_ENDPOINTS.TASKS` undefined.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

const NEAR_JOURNAL_ID = 42;
const LATER_JOURNAL_ID = 43;
const CANCELLED_JOURNAL_ID = 44;

/** A journal `days` days ahead of today in UTC, which is the mocked zone. */
function futureJournal(
  id: number,
  title: string,
  days: number,
  cancelled = false
) {
  const date = addDaysToIsoDate(todayIn('UTC'), days);
  return {
    id: String(id),
    type: 'journals' as const,
    attributes: {
      title,
      content: '',
      event_date_range: {
        start: `${date}T12:00:00Z`,
        end: `${date}T13:00:00Z`,
      },
      types: cancelled ? [JournalType.EVENT] : [JournalType.NOTE],
      ...(cancelled
        ? {
            type_data: {
              [JournalType.EVENT]: {
                calendar_id: 'cal-1',
                is_all_day: true,
                sync_invitees: false,
                private_description: false,
                event_state: 'cancelled',
              },
            },
          }
        : {}),
      contacts: [],
      tags: [],
    },
  };
}

const DEFAULT_JOURNALS = [
  futureJournal(LATER_JOURNAL_ID, 'Trip planning', 30),
  futureJournal(NEAR_JOURNAL_ID, 'Weekly review', 3),
];

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function retargetOk(): Response {
  return jsonResponse(200, {
    data: {
      type: 'tasks',
      id: '1',
      attributes: { status: TaskStatus.NOT_DONE },
    },
  });
}

function reopenNotAcknowledged(): Response {
  return jsonResponse(409, {
    errors: [
      {
        status: '409',
        code: 'TASK_REOPEN_NOT_ACKNOWLEDGED',
        detail: 'Task 1 is done. Retargeting it would reopen it as not done.',
      },
    ],
  });
}

const NOT_FUTURE_DETAIL =
  'The due journal (ID 42) is dated 2020-01-01, which is not after today (2026-08-23) in your timezone.';

function dueJournalNotFuture(): Response {
  return jsonResponse(400, {
    errors: [
      {
        status: '400',
        code: 'TASK_DUE_JOURNAL_NOT_FUTURE',
        detail: NOT_FUTURE_DETAIL,
      },
    ],
  });
}

/** A retarget the test holds open, so "in flight" is a state it can assert on. */
function heldResponse(): { response: Promise<Response>; release: () => void } {
  let release: () => void = () => undefined;
  const response = new Promise<Response>(resolve => {
    release = () => resolve(retargetOk());
  });
  return { response, release };
}

function serverError(): Response {
  return jsonResponse(500, {
    errors: [
      { status: '500', code: 'INTERNAL_ERROR', detail: 'Something broke' },
    ],
  });
}

interface Harness {
  /** Responses the retarget endpoint gives, in order. */
  retargetResponses: (Response | Promise<Response>)[];
  /** The bodies the retarget endpoint was sent, in order. */
  retargetBodies: Record<string, unknown>[];
  /**
   * Whether the endpoint behaves the way the service does for a *done* task:
   * refusing any retarget that does not carry the acknowledgement.
   */
  refusesUnacknowledgedReopen: boolean;
}

function routeFetch(
  harness: Harness,
  journals: ReturnType<typeof futureJournal>[]
) {
  mockFetch.mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.includes('/api/user-settings')) {
        return jsonResponse(200, {
          data: {
            type: 'user-settings',
            id: 'u1',
            attributes: { timezone: 'UTC' },
          },
        });
      }

      if (url.includes('/retarget')) {
        const body = JSON.parse(String(init?.body)) as {
          data: { attributes: { acknowledge_reopen: boolean } };
        };
        harness.retargetBodies.push(body as unknown as Record<string, unknown>);

        // The gate is answered from what was *sent*, not from where we are in
        // a queue. A component that acknowledged on the first request would
        // otherwise still walk through every confirmation test while skipping
        // the confirmation entirely against a real server.
        if (
          harness.refusesUnacknowledgedReopen &&
          !body.data.attributes.acknowledge_reopen
        ) {
          return reopenNotAcknowledged();
        }
        return (await harness.retargetResponses.shift()) ?? retargetOk();
      }

      if (url.includes('/api/journals')) {
        return jsonResponse(200, {
          data: journals,
          meta: { total: journals.length },
        });
      }

      throw new Error(`unexpected request: ${url}`);
    }
  );
}

function renderDialog(
  task: JournalTaskResource = createMockJournalTask(),
  journals = DEFAULT_JOURNALS
) {
  const harness: Harness = {
    retargetResponses: [],
    retargetBodies: [],
    refusesUnacknowledgedReopen: task.attributes.status === TaskStatus.DONE,
  };
  routeFetch(harness, journals);

  const queryClient = createTestQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RetargetTaskDialog task={task} />
    </QueryClientProvider>
  );

  return { harness, queryClient, user: userEvent.setup(), ...view };
}

/** Open the dialog and wait for the picker to have something to offer. */
async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('journal-task-action-retarget'));
  await screen.findByRole('dialog');
  await waitFor(() =>
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0)
  );
}

async function chooseNearJournal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
  );
}

function submitButton(): HTMLElement {
  return screen.getByTestId('retarget-dialog-submit');
}

const LAPSED_TASK = createMockJournalTask({
  status: TaskStatus.NOT_DONE,
  lapsed: true,
  lapse_reason: LapseReason.DATE_PASSED,
});

const CANCELLED_TASK = createMockJournalTask({
  status: TaskStatus.CANCELLED,
});

const DONE_TASK = createMockJournalTask({ status: TaskStatus.DONE });

describe('RetargetTaskDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('the trigger', () => {
    it('offers a lapsed task a resurrection', () => {
      renderDialog(LAPSED_TASK);

      expect(
        screen.getByTestId('journal-task-action-retarget')
      ).toHaveAccessibleName(/resurrect/i);
    });

    /**
     * The row Phase 17 gives no status action at all. If this trigger were not
     * here, a cancelled task would have no way out but deletion.
     */
    it('offers a cancelled task a resurrection', () => {
      renderDialog(CANCELLED_TASK);

      expect(
        screen.getByTestId('journal-task-action-retarget')
      ).toHaveAccessibleName(/resurrect/i);
    });

    it('offers a live task a reschedule instead', () => {
      renderDialog(createMockJournalTask());

      expect(
        screen.getByTestId('journal-task-action-retarget')
      ).toHaveAccessibleName(/reschedule/i);
    });

    it('can be disabled while another write against the task is in flight', () => {
      const harness: Harness = {
        retargetResponses: [],
        retargetBodies: [],
        refusesUnacknowledgedReopen: false,
      };
      routeFetch(harness, DEFAULT_JOURNALS);
      render(
        <QueryClientProvider client={createTestQueryClient()}>
          <RetargetTaskDialog task={createMockJournalTask()} disabled />
        </QueryClientProvider>
      );

      expect(screen.getByTestId('journal-task-action-retarget')).toBeDisabled();
    });
  });

  describe('resurrecting a lapsed task', () => {
    it('sends the chosen journal without the reopen acknowledgement', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(harness.retargetBodies).toHaveLength(1));
      expect(harness.retargetBodies[0]).toEqual({
        data: {
          type: 'task-retarget',
          attributes: {
            due_journal_id: NEAR_JOURNAL_ID,
            acknowledge_reopen: false,
          },
        },
      });
    });

    it('reports the move and closes', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(toast.success).toHaveBeenCalledWith(
        SUCCESS_MESSAGES.TASK_RETARGETED
      );
    });

    it('explains that the task lapsed rather than only that it is moving', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);

      expect(screen.getByRole('dialog')).toHaveTextContent(/lapsed/i);
    });
  });

  describe('resurrecting a cancelled task', () => {
    it('sends the retarget, which is the only exit the service allows', async () => {
      const { user, harness } = renderDialog(CANCELLED_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(harness.retargetBodies).toHaveLength(1));
      expect(
        (
          harness.retargetBodies[0].data as {
            attributes: Record<string, unknown>;
          }
        ).attributes
      ).toMatchObject({ due_journal_id: NEAR_JOURNAL_ID });
    });

    it('says a new future journal is what brings it back', async () => {
      const { user } = renderDialog(CANCELLED_TASK);

      await open(user);

      expect(screen.getByRole('dialog')).toHaveTextContent(/future journal/i);
    });
  });

  describe('the done-reopen confirmation gate', () => {
    it('asks for confirmation when the service refuses the unacknowledged reopen', async () => {
      const { user, harness } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      const confirmation = await screen.findByTestId('retarget-reopen-confirm');
      expect(harness.retargetBodies[0]).toEqual({
        data: {
          type: 'task-retarget',
          attributes: {
            due_journal_id: NEAR_JOURNAL_ID,
            acknowledge_reopen: false,
          },
        },
      });
      expect(confirmation).toHaveTextContent(/reopen/i);
      expect(confirmation).toHaveTextContent(/not done/i);
      expect(confirmation).toHaveTextContent('Weekly review');
    });

    /**
     * The 409 is the service asking a question, not reporting a failure. A red
     * toast under the confirmation would tell the user something had gone
     * wrong at the exact moment nothing had.
     */
    it('raises no error toast for the refusal', async () => {
      const { user } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await screen.findByTestId('retarget-reopen-confirm');
      expect(toast.error).not.toHaveBeenCalled();
    });

    it('sends nothing further when the reopen is declined', async () => {
      const { user, harness } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.click(screen.getByTestId('retarget-reopen-decline'));

      expect(harness.retargetBodies).toHaveLength(1);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByTestId('future-journal-picker')).toBeInTheDocument();
    });

    it('re-sends the same journal with the acknowledgement once confirmed', async () => {
      const { user, harness } = renderDialog(DONE_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.click(screen.getByTestId('retarget-reopen-accept'));

      await waitFor(() => expect(harness.retargetBodies).toHaveLength(2));
      expect(harness.retargetBodies[1]).toEqual({
        data: {
          type: 'task-retarget',
          attributes: {
            due_journal_id: NEAR_JOURNAL_ID,
            acknowledge_reopen: true,
          },
        },
      });
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });
  });

  describe('the automatic mention link', () => {
    /**
     * "The previous due journal is automatically retained as an intermediate
     * journal" — the one automatic link in the model, and it happens on every
     * retarget rather than only on a deferral, so the dialog says so in every
     * case rather than in one of the four per-case descriptions.
     */
    it.each([
      ['live', createMockJournalTask()],
      ['lapsed', LAPSED_TASK],
      ['cancelled', CANCELLED_TASK],
      ['done', DONE_TASK],
    ])(
      'tells a %s task that the journal it leaves is kept',
      async (_, task) => {
        const { user } = renderDialog(task);

        await open(user);

        expect(screen.getByTestId('retarget-keeps-previous')).toHaveTextContent(
          /mention/i
        );
      }
    );
  });

  describe('the service’s rejection', () => {
    /**
     * The picker judges "future" in the browser, against the timezone it can
     * see; the server judges it against the user's *configured* zone. When the
     * two disagree the server wins, and the answer belongs against the field
     * the user chose in — not only in a toast that says nothing about where.
     */
    it('puts a non-future journal against the field rather than only in a toast', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(dueJournalNotFuture());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      const message = await screen.findByText(new RegExp('not after today'));
      const combobox = screen.getByRole('combobox');
      expect(combobox).toHaveAttribute('aria-invalid', 'true');
      expect(combobox.getAttribute('aria-describedby')).toContain(message.id);
    });

    it('keeps the dialog open with the chosen journal still chosen', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(dueJournalNotFuture());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await screen.findByText(new RegExp('not after today'));
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'true');
    });

    /**
     * Pins that the no-toast exception has not widened past the one refusal it
     * was written for.
     */
    it('leaves an ordinary failure to the toast and stays open', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(serverError());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.queryByTestId('retarget-reopen-confirm')).toBeNull();
    });

    it('refuses to submit with no journal chosen', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);

      await open(user);
      expect(submitButton()).toBeDisabled();

      expect(harness.retargetBodies).toHaveLength(0);
    });
  });

  describe('a failure on the confirmed reopen', () => {
    /**
     * The one path that could strand someone: a confirmed reopen that is then
     * refused leaves a panel offering one button the service has just said no
     * to, with the explanation rendered where the picker is not mounted.
     */
    it('returns to the picker rather than leaving the confirmation up', async () => {
      const { user, harness } = renderDialog(DONE_TASK);
      harness.retargetResponses.push(dueJournalNotFuture());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.click(screen.getByTestId('retarget-reopen-accept'));

      await screen.findByText(new RegExp('not after today'));
      expect(screen.queryByTestId('retarget-reopen-confirm')).toBeNull();
      expect(screen.getByTestId('future-journal-picker')).toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('does the same for an ordinary failure', async () => {
      const { user, harness } = renderDialog(DONE_TASK);
      harness.retargetResponses.push(serverError());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.click(screen.getByTestId('retarget-reopen-accept'));

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(screen.queryByTestId('retarget-reopen-confirm')).toBeNull();
      expect(screen.getByTestId('future-journal-picker')).toBeInTheDocument();
    });

    it('keeps the chosen journal so the move can be retried', async () => {
      const { user, harness } = renderDialog(DONE_TASK);
      harness.retargetResponses.push(serverError());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');
      await user.click(screen.getByTestId('retarget-reopen-accept'));

      await waitFor(() => expect(toast.error).toHaveBeenCalled());
      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'true');
    });
  });

  describe('closing and reopening', () => {
    /**
     * Radix calls `onOpenChange` when it closes the dialog itself, but not when
     * a controlled `open` is set to false from inside — which is how both of
     * this component's own closes work. Without routing them through the same
     * handler the reset never runs, and reopening restores a journal the user
     * has already used.
     */
    it('starts clean after a successful move', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

      await open(user);

      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'false');
      expect(submitButton()).toBeDisabled();
    });

    it('starts clean after Cancel', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(screen.getByTestId('retarget-dialog-cancel'));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

      await open(user);

      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'false');
      expect(submitButton()).toBeDisabled();
    });

    /**
     * The worst of the three: a confirmation the user has already answered
     * reappearing on an unrelated later retarget.
     */
    it('does not reopen straight back into a reopen confirmation', async () => {
      const { user } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.keyboard('{Escape}');
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

      await open(user);

      expect(screen.queryByTestId('retarget-reopen-confirm')).toBeNull();
      expect(screen.getByTestId('future-journal-picker')).toBeInTheDocument();
    });
  });

  /**
   * The window between pressing the button and the server answering. It is
   * short, but everything the dialog shows during it is a claim about a
   * request that has already left.
   */
  describe('while the write is in flight', () => {
    it('locks the picker, so the choice cannot drift out from under the request', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      const held = heldResponse();
      harness.retargetResponses.push(held.response);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(screen.getByRole('combobox')).toBeDisabled());
      await user.click(
        screen.getByTestId(`future-journal-option-${LATER_JOURNAL_ID}`)
      );
      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'true');

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    /**
     * The request cannot be called back, so a dialog that vanished on Cancel
     * and then toasted "Task moved" a second later would report the opposite of
     * what the user had just asked for.
     */
    it('refuses Cancel rather than closing over a request it cannot recall', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      const held = heldResponse();
      harness.retargetResponses.push(held.response);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() =>
        expect(screen.getByTestId('retarget-dialog-cancel')).toBeDisabled()
      );
      await user.click(screen.getByTestId('retarget-dialog-cancel'));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('refuses Escape for the same reason', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      const held = heldResponse();
      harness.retargetResponses.push(held.response);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await waitFor(() =>
        expect(screen.getByTestId('retarget-dialog-cancel')).toBeDisabled()
      );

      await user.keyboard('{Escape}');
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    /**
     * The half the first round's fix missed. Cancel and Escape were refused
     * over a pending write, but the confirmation panel's own way out was not —
     * so a user could press "Reopen and move task", change their mind, press
     * "Keep it done", and watch the task reopen anyway.
     */
    it('refuses "Keep it done" over the acknowledged write it cannot recall', async () => {
      const { user, harness } = renderDialog(DONE_TASK);
      const held = heldResponse();
      harness.retargetResponses.push(held.response);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');
      await user.click(screen.getByTestId('retarget-reopen-accept'));

      await waitFor(() =>
        expect(screen.getByTestId('retarget-reopen-decline')).toBeDisabled()
      );
      await user.click(screen.getByTestId('retarget-reopen-decline'));
      expect(screen.getByTestId('retarget-reopen-confirm')).toBeInTheDocument();

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('lets go again once the write settles', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(serverError());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await waitFor(() => expect(toast.error).toHaveBeenCalled());

      expect(screen.getByTestId('retarget-dialog-cancel')).toBeEnabled();
      expect(screen.getByRole('combobox')).toBeEnabled();

      await user.click(screen.getByTestId('retarget-dialog-cancel'));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });
  });

  /**
   * The picker refuses the journal a task is already due in, but it judges
   * that from a snapshot taken when the journal was picked. The task itself is
   * a prop, so a refresh elsewhere can make the chosen journal the current due
   * journal after the fact — and the service treats naming it as a no-op: a
   * 200 that moved nothing, and for a done task a reopen that never happened.
   */
  describe('when the task is refreshed under an open dialog', () => {
    it('stops the move once the chosen journal becomes the current due journal', async () => {
      const { user, harness, rerender, queryClient } =
        renderDialog(LAPSED_TASK);

      await open(user);
      await chooseNearJournal(user);
      expect(submitButton()).toBeEnabled();

      // The task now says it is due where the user has just chosen.
      rerender(
        <QueryClientProvider client={queryClient}>
          <RetargetTaskDialog
            task={createMockJournalTask({
              status: TaskStatus.NOT_DONE,
              lapsed: true,
              lapse_reason: LapseReason.DATE_PASSED,
              due_journal_id: NEAR_JOURNAL_ID,
              due_journal: createMockTaskJournalRef({
                id: NEAR_JOURNAL_ID,
                title: 'Weekly review',
              }),
            })}
          />
        </QueryClientProvider>
      );

      expect(submitButton()).toBeDisabled();
      expect(harness.retargetBodies).toHaveLength(0);
    });
  });

  describe('focus management', () => {
    it('starts on the search box, so a keyboard user can type straight away', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);

      await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
    });

    it('moves to the confirmation when the reopen gate opens', async () => {
      const { user } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() =>
        expect(screen.getByTestId('retarget-reopen-accept')).toHaveFocus()
      );
    });

    it('returns to the search box when the reopen is declined', async () => {
      const { user, harness } = renderDialog(DONE_TASK);

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await screen.findByTestId('retarget-reopen-confirm');

      await user.click(screen.getByTestId('retarget-reopen-decline'));

      await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
      expect(harness.retargetBodies).toHaveLength(1);
    });

    it('moves to the field the service rejected', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(dueJournalNotFuture());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await screen.findByText(new RegExp('not after today'));
      await waitFor(() => expect(screen.getByRole('combobox')).toHaveFocus());
    });

    it('returns to the trigger when the dialog closes', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);
      await user.keyboard('{Escape}');

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      await waitFor(() =>
        expect(screen.getByTestId('journal-task-action-retarget')).toHaveFocus()
      );
    });
  });

  describe('what the dialog must never become', () => {
    /**
     * The specification's fifth invariant: the due journal must be an existing
     * journal, so "the product must not offer a bare date picker, and must not
     * silently create a journal to hold a task".
     */
    it('offers no date input anywhere', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);

      const dialog = screen.getByRole('dialog');
      expect(dialog.querySelector('input[type="date"]')).toBeNull();
      expect(dialog.querySelector('input[type="datetime-local"]')).toBeNull();
      expect(dialog.querySelector('input[type="month"]')).toBeNull();
    });

    it('sends a journal id and nothing resembling a date', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK);
      harness.retargetResponses.push(retargetOk());

      await open(user);
      await chooseNearJournal(user);
      await user.click(submitButton());

      await waitFor(() => expect(harness.retargetBodies).toHaveLength(1));
      const attributes = (
        harness.retargetBodies[0].data as {
          attributes: Record<string, unknown>;
        }
      ).attributes;
      expect(Object.keys(attributes).sort()).toEqual([
        'acknowledge_reopen',
        'due_journal_id',
      ]);
    });

    /**
     * The service treats a retarget naming the journal a task is **already**
     * due in as a no-op: nothing is validated, nothing is written, and no
     * acknowledgement is asked for. A done task offered its own due journal
     * would therefore answer 200, stay done, and be reported as moved — with
     * the confirmation the specification requires never shown.
     */
    it('does not offer the journal the task is already due in', async () => {
      const alreadyDue = createMockJournalTask({
        status: TaskStatus.DONE,
        due_journal_id: NEAR_JOURNAL_ID,
        due_journal: createMockTaskJournalRef({
          id: NEAR_JOURNAL_ID,
          title: 'Weekly review',
        }),
      });
      const { user, harness } = renderDialog(alreadyDue);

      await open(user);
      const current = screen.getByTestId(
        `future-journal-option-${NEAR_JOURNAL_ID}`
      );
      await user.click(current);

      expect(current).toHaveAttribute('aria-disabled', 'true');
      expect(current).toHaveTextContent(/already due here/i);
      expect(submitButton()).toBeDisabled();
      expect(harness.retargetBodies).toHaveLength(0);
    });

    it('does not offer a cancelled journal as somewhere to be due', async () => {
      const { user, harness } = renderDialog(LAPSED_TASK, [
        ...DEFAULT_JOURNALS,
        futureJournal(CANCELLED_JOURNAL_ID, 'Cancelled standup', 5, true),
      ]);

      await open(user);
      const cancelled = screen.getByTestId(
        `future-journal-option-${CANCELLED_JOURNAL_ID}`
      );
      await user.click(cancelled);

      expect(cancelled).toHaveAttribute('aria-disabled', 'true');
      expect(submitButton()).toBeDisabled();
      expect(harness.retargetBodies).toHaveLength(0);
    });
  });

  describe('accessibility', () => {
    it('names and explains itself for the case it is handling', async () => {
      const { user } = renderDialog(DONE_TASK);

      await open(user);

      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveAccessibleName(/reopen/i);
      expect(dialog).toHaveAccessibleDescription(/not done/i);
    });

    it('names the task it is about, not merely “this task”', async () => {
      const { user } = renderDialog(
        createMockJournalTask({
          text: 'Return Sarah’s book',
          status: TaskStatus.NOT_DONE,
          due_journal: createMockTaskJournalRef({ title: 'Book club' }),
        })
      );

      await open(user);

      expect(screen.getByRole('dialog')).toHaveTextContent(
        'Return Sarah’s book'
      );
    });

    it('labels the picker as the due-journal field', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);

      expect(screen.getByRole('combobox')).toHaveAccessibleName(/journal/i);
    });

    it('keeps the option list reachable from the field it belongs to', async () => {
      const { user } = renderDialog(LAPSED_TASK);

      await open(user);

      const listbox = within(screen.getByRole('dialog')).getByRole('listbox');
      expect(screen.getByRole('combobox')).toHaveAttribute(
        'aria-controls',
        listbox.id
      );
    });
  });
});
