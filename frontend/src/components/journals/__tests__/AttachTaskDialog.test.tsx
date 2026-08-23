/**
 * @jest-environment jsdom
 */

/**
 * Tests for AttachTaskDialog — mentioning an existing task in this journal.
 *
 * The criterion these are written against is the third one: "the task picker
 * for attaching is scoped and searchable rather than listing every task —
 * there is no global task list, and this affordance must not become one."
 * There is no global task-search endpoint to misuse, so the assertions are
 * about *which requests are made*: nothing is listed until a journal is named,
 * and what is listed afterwards comes from that journal and no other. A suite
 * that only checked what appeared on screen would still pass if the picker
 * fetched every journal's tasks and filtered them in the browser.
 *
 * `fetch` is spied rather than the hooks mocked, for the same reason: the
 * request is the thing being asserted.
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { AttachTaskDialog } from '../AttachTaskDialog';
import { createMockJournal, createTestQueryClient } from '../test-helpers';
import {
  createMockJournalTask,
  createMockTaskJournalRef,
} from '../test-helpers';
import { TaskStatus } from '@/types/tasks';
import type { JournalTaskResource, JournalTasksResponse } from '@/types/tasks';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` narrows `@/lib/constants` to the endpoints the auth tests
// need, which would leave `API_ENDPOINTS.TASKS` undefined.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const { toast } = jest.requireMock('sonner') as {
  toast: { success: jest.Mock; error: jest.Mock };
};

/** The journal being viewed — the one a mention would be attached to. */
const THIS_JOURNAL = '7';

/** The journal the task lives on, which the user has to name first. */
const SOURCE_JOURNAL = '9';

/** A third journal, which nothing in these tests should ever request. */
const OTHER_JOURNAL = '11';

const PERMIT = createMockJournalTask({
  id: '1',
  text: 'Print the permit',
  due_journal: createMockTaskJournalRef({
    id: Number(SOURCE_JOURNAL),
    title: 'Trip planning',
  }),
});

const BOOK = createMockJournalTask({
  id: '2',
  text: "Return Sarah's book",
  status: TaskStatus.DONE,
});

/** Already linked to the journal being viewed, so it must not be offered. */
const ALREADY_HERE = createMockJournalTask({
  id: '5',
  text: 'Already mentioned here',
});

function listing(tasks: JournalTaskResource[]): JournalTasksResponse {
  return {
    data: tasks,
    meta: {
      groups: {
        due: tasks.map(task => Number(task.id)),
        created: [],
        mentioned: [],
      },
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function noContentResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: jest.fn().mockRejectedValue(new SyntaxError('no body')),
  } as unknown as Response;
}

function errorResponse(status: number, code: string, detail: string): Response {
  return {
    ok: false,
    status,
    json: jest.fn().mockResolvedValue({
      errors: [{ status: String(status), code, detail }],
    }),
  } as unknown as Response;
}

/** The journal search answer the combobox reads. */
function journalSearchResponse() {
  return {
    data: [
      {
        ...createMockJournal({ title: 'Trip planning' }),
        id: SOURCE_JOURNAL,
      },
      { ...createMockJournal({ title: 'Other journal' }), id: OTHER_JOURNAL },
      // The journal being viewed, deliberately in the answer: the endpoint has
      // no idea which journal the dialog is on, so it will come back from any
      // search that matches it, and the exclusion is what must keep it off the
      // list.
      {
        ...createMockJournal({ title: 'Trip aftermath (this journal)' }),
        id: THIS_JOURNAL,
      },
    ],
    meta: { total: 3, page: 1, size: 20, pages: 1 },
  };
}

/**
 * Route every request by URL rather than by call order.
 *
 * The dialog makes a search request, a listing request and a write, and the
 * search fires on a debounce — an ordered queue of `mockResolvedValueOnce`
 * would be asserting the timing of a debounce rather than the behaviour.
 */
function routeFetch(
  overrides: {
    tasks?: Record<string, Response>;
    write?: Response;
  } = {}
) {
  mockFetch.mockImplementation((input, init) => {
    const url = String(input);
    const method = String((init as RequestInit | undefined)?.method ?? 'GET');

    if (method !== 'GET') {
      return Promise.resolve(overrides.write ?? noContentResponse());
    }
    if (url.startsWith('/api/journals?search=')) {
      return Promise.resolve(jsonResponse(journalSearchResponse()));
    }

    const tasksFor = /^\/api\/journals\/(\d+)\/tasks$/.exec(url);
    if (tasksFor) {
      const journalId = tasksFor[1];
      const answer = overrides.tasks?.[journalId];
      return Promise.resolve(answer ?? jsonResponse(listing([])));
    }

    return Promise.resolve(jsonResponse({ data: [], meta: {} }));
  });
}

function renderDialog(linkedTaskIds: readonly string[] = []) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <AttachTaskDialog
        journalId={THIS_JOURNAL}
        linkedTaskIds={linkedTaskIds}
      />
    </QueryClientProvider>
  );
}

/** Open the dialog and return the user-event instance driving it. */
async function openDialog(linkedTaskIds: readonly string[] = []) {
  const user = userEvent.setup();
  renderDialog(linkedTaskIds);

  await user.click(screen.getByRole('button', { name: /attach task/i }));
  await screen.findByRole('dialog');

  return user;
}

/** Name the journal the task is on, as the first step asks. */
async function chooseSourceJournal(
  user: ReturnType<typeof userEvent.setup>,
  title = 'Trip planning'
) {
  await user.type(screen.getByLabelText('Journal the task is on'), 'Trip');
  await user.click(
    await screen.findByRole('button', { name: new RegExp(title) })
  );
}

/** Every request that was not a plain read. */
function writes() {
  return mockFetch.mock.calls.filter(([, init]) =>
    ['POST', 'PATCH', 'DELETE'].includes(
      String((init as RequestInit | undefined)?.method ?? 'GET')
    )
  );
}

/** Every URL a GET was issued for. */
function reads(): string[] {
  return mockFetch.mock.calls
    .filter(
      ([, init]) =>
        String((init as RequestInit | undefined)?.method ?? 'GET') === 'GET'
    )
    .map(([input]) => String(input));
}

beforeEach(() => {
  jest.clearAllMocks();
  routeFetch();
});

describe('AttachTaskDialog', () => {
  describe('the picker is scoped, not a task list', () => {
    /**
     * The heart of criterion 3. There is no endpoint that lists every task, and
     * this asserts the dialog does not assemble one out of the endpoints there
     * are: with the dialog open and no journal named, no listing has been
     * requested at all.
     */
    it('lists nothing, and asks for nothing, until a journal is named', async () => {
      await openDialog();

      expect(screen.queryAllByRole('radio')).toEqual([]);
      expect(reads().filter(url => url.includes('/tasks'))).toEqual([]);
      expect(
        screen.getByText(/find the journal the task is on/i)
      ).toBeInTheDocument();
    });

    it("lists the chosen journal's tasks and requests no other journal's", async () => {
      routeFetch({
        tasks: {
          [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])),
          [OTHER_JOURNAL]: jsonResponse(
            listing([
              createMockJournalTask({ id: '3', text: 'Somewhere else' }),
            ])
          ),
        },
      });
      const user = await openDialog();

      await chooseSourceJournal(user);

      expect(
        await screen.findByRole('radio', { name: /Print the permit/ })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('radio', { name: /Return Sarah's book/ })
      ).toBeInTheDocument();
      expect(screen.queryByText('Somewhere else')).not.toBeInTheDocument();

      const listings = reads().filter(url => url.includes('/tasks'));
      expect(listings).toEqual([`/api/journals/${SOURCE_JOURNAL}/tasks`]);
    });

    /**
     * The second of the two exclusions decision 3 names, and the one with
     * nothing else standing behind it: a task on the journal being viewed is
     * already linked here, so offering that journal as a *source* could only
     * lead to a no-op or a 409.
     */
    it('does not offer the journal being viewed as a source', async () => {
      const user = await openDialog();

      await user.type(screen.getByLabelText('Journal the task is on'), 'Trip');

      expect(
        await screen.findByRole('button', { name: /Trip planning/ })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /Trip aftermath/ })
      ).not.toBeInTheDocument();
    });

    /**
     * The combobox reports `onClear` only when its input goes fully empty, so
     * editing one journal's title into another query left the field showing one
     * journal while the list underneath still held the other one's tasks — and
     * a task could be attached from a source the user believed they had moved
     * off. Found in review.
     */
    it('puts the chosen journal down when the search is typed over', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );

      // Typed *onto* the chosen title rather than cleared first: clearing
      // empties the input, which fires the combobox's own `onClear` and would
      // let this pass without the guard the test is named after.
      const input = screen.getByLabelText('Journal the task is on');
      await user.type(input, ' beach');

      expect(screen.queryAllByRole('radio')).toEqual([]);
      // Every character survives. The combobox re-syncs its input from its
      // `value` prop, so a value derived from the chosen journal would empty
      // the box on the keystroke that put the journal down — typing "Beach"
      // would search for "each".
      expect(input).toHaveValue('Trip planning beach');
      expect(screen.getByTestId('attach-dialog-situation')).toHaveTextContent(
        /find the journal the task is on/i
      );
      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeDisabled();
      expect(writes()).toEqual([]);
    });

    it('keeps a replacement query whole when it lands on the first keystroke', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await screen.findByRole('radio', { name: /Print the permit/ });

      // A whole-value replacement — select-all-and-type, or a paste — driven
      // directly, because it is the case that loses the most: the *first*
      // change both replaces the query and puts the chosen journal down, so a
      // `value` prop derived from the journal would hand the box back empty.
      const input = screen.getByLabelText('Journal the task is on');
      fireEvent.change(input, { target: { value: 'B' } });

      await waitFor(() => {
        expect(screen.queryAllByRole('radio')).toEqual([]);
      });
      expect(input).toHaveValue('B');
    });

    it('narrows the chosen journal down by a filter over its own tasks', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await screen.findByRole('radio', { name: /Print the permit/ });

      await user.type(screen.getByLabelText('Filter tasks'), 'permit');

      expect(
        screen.getByRole('radio', { name: /Print the permit/ })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('radio', { name: /Return Sarah's book/ })
      ).not.toBeInTheDocument();
      // Filtering is over the tasks already in hand, not a second request.
      expect(reads().filter(url => url.includes('/tasks'))).toHaveLength(1);
    });

    /**
     * Decision 11. Leaving the choice made would arm the submit button over a
     * task no longer on screen — the dialog would be about to mention
     * something the user could not see it was about to mention.
     */
    it('clears a choice the filter has narrowed off the screen', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );
      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeEnabled();

      await user.type(screen.getByLabelText('Filter tasks'), 'book');
      // Clearing the filter is what makes this test about the *choice* rather
      // than about the option list: while the filter hides it, the submit
      // guard would disable the button anyway, so only bringing the option
      // back can tell a cleared choice from a merely hidden one.
      await user.clear(screen.getByLabelText('Filter tasks'));

      expect(
        await screen.findByRole('radio', { name: /Print the permit/ })
      ).not.toBeChecked();
      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeDisabled();
      expect(writes()).toEqual([]);
    });

    it('says so rather than emptying silently when a filter matches nothing', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await screen.findByRole('radio', { name: /Print the permit/ });

      await user.type(screen.getByLabelText('Filter tasks'), 'nothing matches');

      expect(screen.queryAllByRole('radio')).toEqual([]);
      expect(screen.getByRole('status')).toHaveTextContent(/no tasks match/i);
    });

    /**
     * Both refusals the server would give, kept off the screen: a task already
     * mentioned here is a no-op, and one anchored here is a 409.
     */
    it('does not offer a task already linked to this journal', async () => {
      routeFetch({
        tasks: {
          [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, ALREADY_HERE])),
        },
      });
      const user = await openDialog([ALREADY_HERE.id]);

      await chooseSourceJournal(user);

      expect(
        await screen.findByRole('radio', { name: /Print the permit/ })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('radio', { name: /Already mentioned here/ })
      ).not.toBeInTheDocument();
    });

    it('says when every task on that journal is already linked here', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([ALREADY_HERE])) },
      });
      const user = await openDialog([ALREADY_HERE.id]);

      await chooseSourceJournal(user);

      expect(await screen.findByRole('status')).toHaveTextContent(
        /already linked to this journal/i
      );
    });

    it('says when the chosen journal holds no tasks at all', async () => {
      routeFetch({ tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([])) } });
      const user = await openDialog();

      await chooseSourceJournal(user);

      expect(await screen.findByRole('status')).toHaveTextContent(
        /no tasks on it/i
      );
    });

    it('reports a listing it could not read rather than showing an empty picker', async () => {
      routeFetch({
        tasks: {
          [SOURCE_JOURNAL]: errorResponse(500, 'INTERNAL_ERROR', 'boom'),
        },
      });
      const user = await openDialog();

      await chooseSourceJournal(user);

      expect(await screen.findByRole('status')).toHaveTextContent(
        /could not be loaded/i
      );
    });
  });

  describe('attaching', () => {
    it('mentions the chosen task in this journal and closes', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);

      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );
      await user.click(
        screen.getByRole('button', { name: 'Attach to this journal' })
      );

      await waitFor(() => {
        expect(writes()).toHaveLength(1);
      });
      const [url, init] = writes()[0];
      expect(String(url)).toBe(
        `/api/tasks/${PERMIT.id}/relationships/intermediate-journals`
      );
      expect((init as RequestInit).method).toBe('POST');
      expect(JSON.parse(String((init as RequestInit).body))).toEqual({
        data: { type: 'journals', id: THIS_JOURNAL },
      });

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(toast.success).toHaveBeenCalledWith('Journal linked successfully');
    });

    it('offers no way to submit until a task is chosen, and writes nothing', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
      });
      const user = await openDialog();

      const submit = screen.getByRole('button', {
        name: 'Attach to this journal',
      });
      expect(submit).toBeDisabled();

      await chooseSourceJournal(user);
      await screen.findByRole('radio', { name: /Print the permit/ });
      expect(submit).toBeDisabled();

      await user.click(screen.getByRole('radio', { name: /Print the permit/ }));
      expect(submit).toBeEnabled();
      expect(writes()).toEqual([]);
    });

    /**
     * The same rule as Phase 18's "re-read the condition against the live
     * prop", met here through `linkedTaskIds`: a write elsewhere on the page
     * can refresh this journal's listing under an open dialog and make the
     * chosen task one the journal already holds. Submitting it then sends the
     * request this dialog exists to keep off the wire.
     */
    it('disarms a choice the journal has acquired while the dialog was open', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = userEvent.setup();
      // One client across both renders: a fresh one would empty the option list
      // by dropping the cached listing, and the test would pass for a reason
      // that has nothing to do with the rule it is named after.
      const queryClient = createTestQueryClient();
      const view = render(
        <QueryClientProvider client={queryClient}>
          <AttachTaskDialog journalId={THIS_JOURNAL} linkedTaskIds={[]} />
        </QueryClientProvider>
      );
      await user.click(screen.getByRole('button', { name: /attach task/i }));
      await screen.findByRole('dialog');
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );
      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeEnabled();

      view.rerender(
        <QueryClientProvider client={queryClient}>
          <AttachTaskDialog
            journalId={THIS_JOURNAL}
            linkedTaskIds={[PERMIT.id]}
          />
        </QueryClientProvider>
      );

      expect(
        screen.queryByRole('radio', { name: /Print the permit/ })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeDisabled();
      expect(writes()).toEqual([]);
    });

    /**
     * The exclusion above is computed from a cache, and a cache can be stale: a
     * task retargeted onto this journal from somewhere else is an anchor here
     * by the time the request lands. The server is the authority, so its
     * refusal is rendered against the field the user chose in — Phase 18's rule
     * for the future-date refusal, and the toast is left alone for the same
     * reason.
     */
    it('reports an anchor refusal against the task field and stays open', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
        write: errorResponse(
          409,
          'TASK_JOURNAL_IS_ANCHOR',
          'Journal 7 is the due journal of task 1'
        ),
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );

      await user.click(
        screen.getByRole('button', { name: 'Attach to this journal' })
      );

      expect(
        await screen.findByText('Journal 7 is the due journal of task 1')
      ).toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(toast.error).toHaveBeenCalledWith(
        'Journal 7 is the due journal of task 1'
      );
    });

    it('keeps the dialog open on any other failure so the choice can be retried', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
        write: errorResponse(500, 'INTERNAL_ERROR', 'Something broke'),
      });
      const user = await openDialog();
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );

      await user.click(
        screen.getByRole('button', { name: 'Attach to this journal' })
      );

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith('Something broke');
      });
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  /**
   * The same stance the retarget dialog takes, and for the same reason: the
   * request has already left, so a dialog that vanished on Cancel and then
   * toasted "Journal linked" a second later would report the opposite of what
   * the user had just asked for.
   */
  describe('while the write is in flight', () => {
    async function submitAndHold() {
      let release: () => void = () => undefined;
      const held = new Promise<Response>(resolve => {
        release = () => resolve(noContentResponse());
      });

      mockFetch.mockImplementation((input, init) => {
        const method = String(
          (init as RequestInit | undefined)?.method ?? 'GET'
        );
        if (method !== 'GET') return held;

        const url = String(input);
        if (url.startsWith('/api/journals?search=')) {
          return Promise.resolve(jsonResponse(journalSearchResponse()));
        }
        if (url === `/api/journals/${SOURCE_JOURNAL}/tasks`) {
          return Promise.resolve(jsonResponse(listing([PERMIT])));
        }
        return Promise.resolve(jsonResponse({ data: [], meta: {} }));
      });

      const user = await openDialog();
      await chooseSourceJournal(user);
      await user.click(
        await screen.findByRole('radio', { name: /Print the permit/ })
      );
      await user.click(
        screen.getByRole('button', { name: 'Attach to this journal' })
      );

      return { user, release };
    }

    /**
     * Cancel is *disabled* rather than merely refused, which is the difference
     * between a control that does nothing and a control that says it will do
     * nothing. The Escape case below is what exercises the guard itself.
     */
    it('locks Cancel, so the dialog cannot be dismissed over the write', async () => {
      const { user, release } = await submitAndHold();

      await waitFor(() => {
        expect(screen.getByTestId('attach-dialog-cancel')).toBeDisabled();
      });
      await user.click(screen.getByTestId('attach-dialog-cancel'));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      release();
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('refuses Escape', async () => {
      const { user, release } = await submitAndHold();

      await waitFor(() => {
        expect(screen.getByTestId('attach-dialog-cancel')).toBeDisabled();
      });
      await user.keyboard('{Escape}');
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      release();
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('locks the choice, so the refusal cannot land against a task the request never named', async () => {
      const { release } = await submitAndHold();

      await waitFor(() => {
        expect(
          screen.getByRole('radio', { name: /Print the permit/ })
        ).toBeDisabled();
      });

      release();
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });
  });

  /**
   * Escape belongs to whichever thing is open. The combobox closes its own
   * dropdown and lets the key carry on to Radix's dismissable layer, so
   * without a guard one press dismisses a dropdown *and* throws the dialog
   * away — with the journal, the filter and the chosen task in it.
   */
  describe('Escape', () => {
    it('closes the search dropdown without closing the dialog', async () => {
      const user = await openDialog();
      const input = screen.getByLabelText('Journal the task is on');

      await user.type(input, 'Trip');
      await screen.findByRole('button', { name: /Trip planning/ });
      expect(input).toHaveAttribute('aria-expanded', 'true');

      await user.keyboard('{Escape}');

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(input).toHaveAttribute('aria-expanded', 'false');
    });

    it('closes the dialog once no dropdown is open', async () => {
      const user = await openDialog();
      const input = screen.getByLabelText('Journal the task is on');

      await user.type(input, 'Trip');
      await screen.findByRole('button', { name: /Trip planning/ });
      await user.keyboard('{Escape}');
      await user.keyboard('{Escape}');

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });
  });

  describe('accessibility', () => {
    /**
     * Radix's own default would land here too, since the search box is the
     * first tabbable node today — so this pins *where focus ends up* rather
     * than proving the override is what put it there. It is the guarantee
     * worth holding: a control added above the picker later must not silently
     * take the focus, and this fails when one does.
     */
    it('opens with focus in the journal search box', async () => {
      await openDialog();

      await waitFor(() => {
        expect(screen.getByLabelText('Journal the task is on')).toHaveFocus();
      });
    });

    it('names the choice as a radio group and reaches it from the keyboard', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);

      const group = await screen.findByRole('radiogroup', {
        name: 'Task to attach',
      });
      const options = within(group).getAllByRole('radio');
      expect(options).toHaveLength(2);

      options[0].focus();
      await user.keyboard(' ');
      expect(options[0]).toBeChecked();

      // Arrow keys move between the options and Space chooses the one focus
      // has reached — the group is operable without a pointer, which is what
      // using a real radio group rather than a hand-rolled listbox buys.
      await user.keyboard('{ArrowDown}');
      expect(options[1]).toHaveFocus();

      await user.keyboard(' ');
      expect(options[1]).toBeChecked();
      expect(options[0]).not.toBeChecked();

      expect(
        screen.getByRole('button', { name: 'Attach to this journal' })
      ).toBeEnabled();
    });

    it('says how many tasks are on offer rather than changing silently', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT, BOOK])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);

      expect(await screen.findByRole('status')).toHaveTextContent(/2 tasks/i);
    });

    it('describes each option by its status and the journal it is due in', async () => {
      routeFetch({
        tasks: { [SOURCE_JOURNAL]: jsonResponse(listing([PERMIT])) },
      });
      const user = await openDialog();
      await chooseSourceJournal(user);

      const option = await screen.findByRole('radio', {
        name: /Print the permit/,
      });
      expect(option).toHaveAccessibleName(/Not done/);
      expect(option).toHaveAccessibleName(/Trip planning/);
    });

    it('explains what attaching does, not merely that it can be done', async () => {
      await openDialog();

      expect(
        within(screen.getByRole('dialog')).getByText(/mention/i)
      ).toBeInTheDocument();
    });
  });
});
