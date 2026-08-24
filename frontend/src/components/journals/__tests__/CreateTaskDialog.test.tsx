/**
 * @jest-environment jsdom
 */

/**
 * Tests for creating a task from the journal it arose in.
 *
 * The specification's *Creating a task* is short and every clause of it is a
 * rule this dialog has to keep: the journal being viewed **becomes** the
 * creating journal and "is never chosen separately"; the due journal is picked
 * from the user's future journals and never from a date field; contacts are
 * optional; and a user with no future journals is told so plainly *and offered
 * one to create*, rather than shown an empty picker.
 *
 * **`fetch` is spied rather than the hooks mocked**, because three of those
 * clauses are statements about the request the user's clicks produce — which
 * journal it is addressed to, that no date is ever sent, that "no contacts" is
 * the absence of a field rather than an empty list. A suite that mocked
 * `useCreateTask` would assert an argument object and would pass just as well
 * if the request went to the wrong journal.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { CreateTaskDialog } from '../CreateTaskDialog';
import { createTestQueryClient } from '../test-helpers';
import { addDaysToIsoDate, todayIn } from '@/lib/future-journals';
import { SUCCESS_MESSAGES } from '@/lib/constants';
import { JournalType } from '@/types/journals';

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

/** The journal being viewed — the creating journal, and never a choice. */
const THIS_JOURNAL = '7';

const NEAR_JOURNAL_ID = 42;
const LATER_JOURNAL_ID = 43;

/** A journal `days` days ahead of today in UTC, which is the mocked zone. */
function futureJournal(id: number, title: string, days: number) {
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
      types: [JournalType.NOTE],
      contacts: [],
      tags: [],
    },
  };
}

/**
 * Deliberately **newest first**, which is the order the listing endpoint
 * answers in. The picker is required to offer the nearest journal first, so a
 * fixture already in the wanted order would let a missing sort pass.
 */
const DEFAULT_JOURNALS = [
  futureJournal(LATER_JOURNAL_ID, 'Trip planning', 30),
  futureJournal(NEAR_JOURNAL_ID, 'Weekly review', 3),
];

const SARAH = {
  type: 'contacts' as const,
  id: '11',
  attributes: {
    first_name: 'Sarah',
    last_name: 'Chen',
    is_favourite: false,
    contact_methods: [],
    addresses: [],
    notes: [],
    relationships: [],
  },
};

const RAJ = {
  type: 'contacts' as const,
  id: '12',
  attributes: {
    first_name: 'Raj',
    last_name: 'Patel',
    is_favourite: false,
    contact_methods: [],
    addresses: [],
    notes: [],
    relationships: [],
  },
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function createdOk(): Response {
  return jsonResponse(201, {
    data: {
      type: 'tasks',
      id: '99',
      attributes: {
        text: 'Print the permit',
        status: 'not_done',
        creating_journal_id: Number(THIS_JOURNAL),
        due_journal_id: NEAR_JOURNAL_ID,
        intermediate_journal_ids: [],
      },
    },
  });
}

function apiError(
  status: number,
  code: string,
  detail: string,
  meta?: unknown
) {
  return jsonResponse(status, {
    errors: [
      { status: String(status), code, detail, ...(meta ? { meta } : {}) },
    ],
  });
}

const NOT_FUTURE_DETAIL =
  'The due journal (ID 42) is dated 2020-01-01, which is not after today ' +
  '(2026-08-23) in your timezone.';

/** A create the test holds open, so "in flight" is a state it can assert on. */
function heldResponse(): { response: Promise<Response>; release: () => void } {
  let release: () => void = () => undefined;
  const response = new Promise<Response>(resolve => {
    release = () => resolve(createdOk());
  });
  return { response, release };
}

interface Harness {
  /** Responses the create endpoint gives, in order; `createdOk` after that. */
  createResponses: (Response | Promise<Response>)[];
  /** The bodies the create endpoint was sent, in order. */
  createBodies: Record<string, unknown>[];
  /** The URLs the create endpoint was posted to, in order. */
  createUrls: string[];
}

function routeFetch(
  harness: Harness,
  journals: ReturnType<typeof futureJournal>[],
  contacts: Array<typeof SARAH>,
  /** What the listing answers for a given `search=` term, standing in for the
      endpoint's own filter. */
  journalsForSearch: Record<string, ReturnType<typeof futureJournal>[]> = {}
) {
  mockFetch.mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method ?? 'GET');

      if (url.includes('/api/user-settings')) {
        return jsonResponse(200, {
          data: {
            type: 'user-settings',
            id: 'u1',
            attributes: { timezone: 'UTC' },
          },
        });
      }

      if (url.includes('/api/search/contacts')) {
        return jsonResponse(200, { data: contacts });
      }

      if (method === 'POST' && /\/api\/journals\/\d+\/tasks$/.test(url)) {
        harness.createUrls.push(url);
        harness.createBodies.push(
          JSON.parse(String(init?.body)) as Record<string, unknown>
        );
        return (await harness.createResponses.shift()) ?? createdOk();
      }

      if (url.includes('/api/journals')) {
        const searched = /[?&]search=([^&]*)/.exec(url)?.[1];
        const answer = searched
          ? (journalsForSearch[decodeURIComponent(searched)] ?? [])
          : journals;
        return jsonResponse(200, {
          data: answer,
          meta: { total: answer.length },
        });
      }

      throw new Error(`unexpected request: ${url}`);
    }
  );
}

function renderDialog(
  options: {
    journals?: ReturnType<typeof futureJournal>[];
    contacts?: Array<typeof SARAH>;
    journalsForSearch?: Record<string, ReturnType<typeof futureJournal>[]>;
  } = {}
) {
  const harness: Harness = {
    createResponses: [],
    createBodies: [],
    createUrls: [],
  };
  routeFetch(
    harness,
    options.journals ?? DEFAULT_JOURNALS,
    options.contacts ?? [SARAH, RAJ],
    options.journalsForSearch
  );

  const queryClient = createTestQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <CreateTaskDialog journalId={THIS_JOURNAL} />
    </QueryClientProvider>
  );

  return { harness, queryClient, user: userEvent.setup(), ...view };
}

type User = ReturnType<typeof userEvent.setup>;

function trigger(): HTMLElement {
  return screen.getByTestId('journal-task-action-create');
}

/** Open the dialog and wait for the picker to have something to offer. */
async function open(user: User) {
  await user.click(trigger());
  await screen.findByRole('dialog');
  await waitFor(() =>
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0)
  );
}

/** Open the dialog on a user who has no future journals at all. */
async function openEmpty(user: User) {
  await user.click(trigger());
  await screen.findByRole('dialog');
  await screen.findByTestId('future-journal-empty');
}

async function typeText(user: User, text = 'Print the permit') {
  await user.type(screen.getByTestId('create-task-text'), text);
}

async function chooseNearJournal(user: User) {
  await user.click(
    screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
  );
}

/** The contact search, found by its label — the wiring the form guarantees. */
function contactSearch(): HTMLElement {
  return screen.getByLabelText(/contacts \(optional\)/i);
}

async function chooseContact(user: User, name: RegExp) {
  await user.type(contactSearch(), 'a');
  await user.click(await screen.findByRole('button', { name }));
}

function submitButton(): HTMLElement {
  return screen.getByTestId('create-task-dialog-submit');
}

/** Text, journal and submit — the whole happy path in one line. */
async function fillAndSubmit(user: User) {
  await typeText(user);
  await chooseNearJournal(user);
  await user.click(submitButton());
}

/** The attributes of the one create request that was sent. */
function sentAttributes(harness: Harness): Record<string, unknown> {
  expect(harness.createBodies).toHaveLength(1);
  const body = harness.createBodies[0] as {
    data: { attributes: Record<string, unknown> };
  };
  return body.data.attributes;
}

describe('CreateTaskDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('the affordance', () => {
    it('offers to create a task without opening anything by itself', () => {
      const { harness } = renderDialog();

      expect(trigger()).toHaveAccessibleName(/new task/i);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(harness.createBodies).toEqual([]);
    });

    it('writes nothing merely by being opened', async () => {
      const { harness, user } = renderDialog();

      await open(user);

      expect(harness.createBodies).toEqual([]);
    });
  });

  describe('the creating journal is the journal being viewed', () => {
    /**
     * The criterion — "the creating journal is the journal being viewed and is
     * never presented as a choice" — is only checkable on the **request**. The
     * endpoint takes the creating journal from its path, so a dialog that had
     * got this wrong would look identical on screen.
     */
    it('posts to the journal being viewed', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() =>
        expect(harness.createUrls).toEqual([
          `/api/journals/${THIS_JOURNAL}/tasks`,
        ])
      );
      // Not the due journal, which is the mistake this would be.
      expect(harness.createUrls[0]).not.toContain(`/${NEAR_JOURNAL_ID}/`);
    });

    it('offers no control for choosing where the task is created', async () => {
      const { user } = renderDialog();

      await open(user);

      const dialog = screen.getByRole('dialog');
      // Exactly three inputs: what needs doing, the due-journal search, and
      // the contact search. A fourth would be a field this dialog must not
      // have — a creating-journal picker, or a date.
      expect(within(dialog).getAllByRole('textbox')).toHaveLength(1);
      expect(within(dialog).getAllByRole('combobox')).toHaveLength(2);
      expect(
        within(dialog).queryByLabelText(/created in|creating journal/i)
      ).toBeNull();
    });
  });

  describe('creating a task', () => {
    it('sends the text and the chosen journal, and nothing else', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() => expect(harness.createBodies).toHaveLength(1));
      expect(harness.createBodies[0]).toEqual({
        data: {
          type: 'tasks',
          attributes: {
            text: 'Print the permit',
            due_journal_id: NEAR_JOURNAL_ID,
          },
        },
      });
    });

    it('closes and says so once the task exists', async () => {
      const { user } = renderDialog();

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(toast.success).toHaveBeenCalledWith(SUCCESS_MESSAGES.TASK_CREATED);
    });

    it('refreshes the journal listings the new task belongs on', async () => {
      const { queryClient, user } = renderDialog();
      const invalidate = jest.spyOn(queryClient, 'invalidateQueries');

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() => expect(invalidate).toHaveBeenCalled());
      const keys = invalidate.mock.calls.map(([args]) =>
        JSON.stringify(args?.queryKey)
      );
      expect(keys).toContain(JSON.stringify(['tasks', 'journal']));
    });

    it('sends one request however many times the button is pressed', async () => {
      const held = heldResponse();
      const { harness, user } = renderDialog();
      harness.createResponses.push(held.response);

      await open(user);
      await typeText(user);
      await chooseNearJournal(user);
      await user.click(submitButton());
      await user.click(submitButton());

      expect(harness.createBodies).toHaveLength(1);
      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });
  });

  describe('what the form refuses before it asks the server', () => {
    it('will not submit until a journal has been chosen', async () => {
      const { user } = renderDialog();

      await open(user);
      await typeText(user);

      expect(submitButton()).toBeDisabled();

      await chooseNearJournal(user);
      expect(submitButton()).toBeEnabled();
    });

    it('says what is missing when the text is blank', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await user.type(screen.getByTestId('create-task-text'), '   ');
      await chooseNearJournal(user);
      await user.click(submitButton());

      const message = await screen.findByText(/say what needs doing/i);
      expect(harness.createBodies).toEqual([]);

      // The message names the field it is about, rather than floating beside
      // it: this is the wiring `FormField`/`FormMessage` exist to guarantee.
      const input = screen.getByTestId('create-task-text');
      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(input.getAttribute('aria-describedby') ?? '').toContain(
        message.id
      );
    });
  });

  describe('the due-journal picker', () => {
    /**
     * "Recent and near-future journals first." The fixture is newest-first —
     * the order the listing endpoint answers in — so a dialog that rendered
     * the answer as given would fail this.
     */
    it('offers the nearest journal first', async () => {
      const { user } = renderDialog();

      await open(user);

      expect(
        screen.getAllByRole('option').map(option => option.textContent)
      ).toEqual([
        expect.stringContaining('Weekly review'),
        expect.stringContaining('Trip planning'),
      ]);
    });

    it('searches across future journals as the user types', async () => {
      const { user } = renderDialog({
        // The endpoint filters; this stands in for it, so the assertion below
        // is about what the picker *renders* from a search rather than only
        // about a URL having been requested.
        journalsForSearch: {
          Trip: [futureJournal(LATER_JOURNAL_ID, 'Trip planning', 30)],
        },
      });

      await open(user);
      expect(screen.getAllByRole('option')).toHaveLength(2);

      await user.type(screen.getByTestId('future-journal-search'), 'Trip');

      await waitFor(() =>
        expect(
          screen.getAllByRole('option').map(option => option.textContent)
        ).toEqual([expect.stringContaining('Trip planning')])
      );
      expect(
        mockFetch.mock.calls
          .map(([input]) => String(input))
          .filter(url => url.includes('search=Trip')).length
      ).toBeGreaterThan(0);
    });

    /**
     * The fifth invariant, asserted on the surface that creates the link:
     * "the product must not offer a bare date picker, and must not silently
     * create a journal to hold a task".
     */
    it('offers no date input of any kind', async () => {
      const { user } = renderDialog();

      await open(user);

      const dialog = screen.getByRole('dialog');
      expect(dialog.querySelector('input[type="date"]')).toBeNull();
      expect(dialog.querySelector('input[type="datetime-local"]')).toBeNull();
      expect(dialog.querySelector('input[type="month"]')).toBeNull();
    });

    it('can be operated entirely from the keyboard', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await typeText(user);

      const search = screen.getByTestId('future-journal-search');
      search.focus();
      await user.keyboard('{ArrowDown}');

      // `aria-activedescendant` is what tells a screen reader which option the
      // cursor is on while focus stays in the input.
      const firstOption = screen.getAllByRole('option')[0];
      expect(search).toHaveAttribute('aria-activedescendant', firstOption.id);
      expect(search).toHaveAttribute('aria-expanded', 'true');
      expect(search).toHaveAttribute(
        'aria-controls',
        screen.getByRole('listbox').id
      );

      await user.keyboard('{Enter}');
      expect(firstOption).toHaveAttribute('aria-selected', 'true');

      await user.click(submitButton());
      await waitFor(() =>
        expect(sentAttributes(harness).due_journal_id).toBe(NEAR_JOURNAL_ID)
      );
    });
  });

  describe('with no future journals', () => {
    it('says so and offers to create one, rather than an empty picker', async () => {
      const { user } = renderDialog({ journals: [] });

      await openEmpty(user);

      expect(screen.getByTestId('future-journal-empty')).toBeInTheDocument();
      const offer = screen.getByTestId('future-journal-create-offer');
      expect(offer).toHaveAttribute('href', '/journals/new');
      expect(screen.queryAllByRole('option')).toEqual([]);
    });

    it('cannot be submitted from that state', async () => {
      const { harness, user } = renderDialog({ journals: [] });

      await openEmpty(user);
      await typeText(user);

      expect(submitButton()).toBeDisabled();
      expect(harness.createBodies).toEqual([]);
    });
  });

  describe('contacts are optional', () => {
    it('sends no contacts key at all when none were chosen', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() => expect(harness.createBodies).toHaveLength(1));
      // Not `contact_ids: []`: the attributes forbid extras and "no contacts"
      // is the absence of the field, so an empty list would be a different
      // request saying the same thing.
      expect(sentAttributes(harness)).not.toHaveProperty('contact_ids');
    });

    it('sends the contacts the user chose', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await typeText(user);
      await chooseNearJournal(user);
      await chooseContact(user, /Sarah Chen/);
      await chooseContact(user, /Raj Patel/);
      await user.click(submitButton());

      await waitFor(() => expect(harness.createBodies).toHaveLength(1));
      expect(sentAttributes(harness).contact_ids).toEqual([
        Number(SARAH.id),
        Number(RAJ.id),
      ]);
    });

    it('lets a chosen contact be taken off again', async () => {
      const { harness, user } = renderDialog();

      await open(user);
      await typeText(user);
      await chooseNearJournal(user);
      await chooseContact(user, /Sarah Chen/);

      await user.click(
        screen.getByRole('button', { name: /remove sarah chen/i })
      );
      await user.click(submitButton());

      await waitFor(() => expect(harness.createBodies).toHaveLength(1));
      expect(sentAttributes(harness)).not.toHaveProperty('contact_ids');
    });

    /**
     * The description is true whether or not the field is in error, so it is
     * announced with the input in both states. `FormControl` is what assembles
     * that pair for an ordinary field, and this control cannot be wrapped in
     * one — it would put the ids on the combobox's container rather than on
     * its input.
     */
    it('announces its description with the input, error or not', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(404, 'CONTACT_NOT_FOUND', 'Contact with ID 11 not found')
      );

      await open(user);
      const description = screen.getByText(/anyone this commitment involves/i);
      expect(contactSearch().getAttribute('aria-describedby') ?? '').toContain(
        description.id
      );

      await typeText(user);
      await chooseNearJournal(user);
      await chooseContact(user, /Sarah Chen/);
      await user.click(submitButton());

      const message = await screen.findByText('Contact with ID 11 not found');
      const describedBy =
        contactSearch().getAttribute('aria-describedby') ?? '';
      expect(describedBy).toContain(description.id);
      expect(describedBy).toContain(message.id);
    });

    it('does not offer a contact that has already been chosen', async () => {
      const { user } = renderDialog();

      await open(user);
      await chooseContact(user, /Sarah Chen/);
      await user.type(contactSearch(), 'a');

      // Scoped to the results list: the chosen contact is still on screen as
      // a badge, which is the point — what must not happen is being offered it
      // a second time.
      const results = await screen.findByRole('listbox', {
        name: 'Contact search results',
      });
      expect(
        within(results).queryByRole('button', { name: /Raj Patel/ })
      ).not.toBeNull();
      expect(
        within(results).queryByRole('button', { name: /Sarah Chen/ })
      ).toBeNull();
    });
  });

  describe('what the server refuses lands on the field that caused it', () => {
    it('puts a non-future journal against the due-journal field', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_DUE_JOURNAL_NOT_FUTURE', NOT_FUTURE_DETAIL)
      );

      await open(user);
      await fillAndSubmit(user);

      const message = await screen.findByText(NOT_FUTURE_DETAIL);
      const search = screen.getByTestId('future-journal-search');
      expect(search).toHaveAttribute('aria-invalid', 'true');
      expect(search.getAttribute('aria-describedby') ?? '').toContain(
        message.id
      );
      // Focus goes back to the control the user has to change.
      expect(search).toHaveFocus();
    });

    it('keeps the dialog and the choice while that is corrected', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_DUE_JOURNAL_NOT_FUTURE', NOT_FUTURE_DETAIL)
      );

      await open(user);
      await fillAndSubmit(user);

      await screen.findByText(NOT_FUTURE_DETAIL);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByTestId('create-task-text')).toHaveValue(
        'Print the permit'
      );
      expect(
        screen.getByTestId(`future-journal-option-${NEAR_JOURNAL_ID}`)
      ).toHaveAttribute('aria-selected', 'true');
    });

    /**
     * The toast is not suppressed when the field message is added. A user who
     * has scrolled away from the field would otherwise get no report at all,
     * and the hook raising it covers every other failure too — narrowing it
     * here would widen an exception written for one refusal into a rule about
     * all of them.
     */
    it('reports it in the toast as well', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_DUE_JOURNAL_NOT_FUTURE', NOT_FUTURE_DETAIL)
      );

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(NOT_FUTURE_DETAIL)
      );
    });

    /**
     * The field the refusal is about travels as `meta.field` rather than being
     * read out of the message's `"text: ..."` prefix, so this is the mapping
     * the backend change in this phase exists to make possible.
     */
    it('puts a rejected text against the text field', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_VALIDATION_ERROR', 'text: Task text is required', {
          field: 'text',
        })
      );

      await open(user);
      await fillAndSubmit(user);

      const message = await screen.findByText('text: Task text is required');
      const input = screen.getByTestId('create-task-text');
      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(input.getAttribute('aria-describedby') ?? '').toContain(
        message.id
      );
      expect(input).toHaveFocus();
    });

    it('puts a rejected due journal against the picker, whichever code says so', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(
          400,
          'TASK_VALIDATION_ERROR',
          'due_journal_id: A journal anchor is required',
          { field: 'due_journal_id' }
        )
      );

      await open(user);
      await fillAndSubmit(user);

      await screen.findByText('due_journal_id: A journal anchor is required');
      expect(screen.getByTestId('future-journal-search')).toHaveAttribute(
        'aria-invalid',
        'true'
      );
    });

    it('puts a missing contact against the contacts field', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(404, 'CONTACT_NOT_FOUND', 'Contact with ID 11 not found')
      );

      await open(user);
      await typeText(user);
      await chooseNearJournal(user);
      await chooseContact(user, /Sarah Chen/);
      await user.click(submitButton());

      const message = await screen.findByText('Contact with ID 11 not found');
      expect(contactSearch().getAttribute('aria-describedby') ?? '').toContain(
        message.id
      );
      // `FormMessage` is a plain paragraph rather than a live region, so a
      // message nobody is moved to is one a screen-reader user never hears.
      // Every field refusal in this dialog moves focus, for that reason.
      expect(contactSearch()).toHaveFocus();
    });

    /**
     * A field name this dialog has no input for must not be swallowed. The
     * hook's toast is the report, and the dialog stays open so the user can
     * try again rather than losing what they typed.
     */
    it('does not swallow a refusal it cannot place on a field', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_VALIDATION_ERROR', 'user_id: User ID is required', {
          field: 'user_id',
        })
      );

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('user_id: User ID is required')
      );
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByTestId('create-task-text')).toHaveValue(
        'Print the permit'
      );
      expect(screen.getByTestId('create-task-text')).not.toHaveAttribute(
        'aria-invalid',
        'true'
      );
    });

    /**
     * `meta.field` is a string the *server* chose, and a plain object would
     * answer `map['constructor']` through its prototype with something truthy.
     * The lookup is a `Map`, so a name this form has no input for is a name it
     * has no input for, whatever it happens to be.
     */
    it('places nothing for a field name that is a prototype key', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_VALIDATION_ERROR', 'constructor: nope', {
          field: 'constructor',
        })
      );

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('constructor: nope')
      );
      expect(screen.getByTestId('create-task-text')).not.toHaveAttribute(
        'aria-invalid',
        'true'
      );
      expect(screen.getByTestId('future-journal-search')).not.toHaveAttribute(
        'aria-invalid',
        'true'
      );
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('leaves an unrelated failure to the toast and stays open', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(500, 'INTERNAL_ERROR', 'Something broke')
      );

      await open(user);
      await fillAndSubmit(user);

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('Something broke')
      );
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  describe('opening, closing and reopening', () => {
    /**
     * Radix calls `onOpenChange` when *it* closes the dialog — Escape, the
     * overlay, the close button — but **not** when a controlled `open` is set
     * to false from inside, which is how both of this component's own closes
     * work. So all three go through one handler, or a reopened dialog would
     * restore what the last one had typed and chosen.
     */
    it('forgets what was typed when cancelled', async () => {
      const { user } = renderDialog();

      await open(user);
      await typeText(user);
      await chooseNearJournal(user);
      await user.click(screen.getByTestId('create-task-dialog-cancel'));

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      await open(user);
      expect(screen.getByTestId('create-task-text')).toHaveValue('');
      expect(submitButton()).toBeDisabled();
    });

    it('forgets what was typed when dismissed with Escape', async () => {
      const { user } = renderDialog();

      await open(user);
      await typeText(user);
      await user.keyboard('{Escape}');

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      await open(user);
      expect(screen.getByTestId('create-task-text')).toHaveValue('');
    });

    it('forgets the last task after one is created', async () => {
      const { user } = renderDialog();

      await open(user);
      await fillAndSubmit(user);
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

      await open(user);
      expect(screen.getByTestId('create-task-text')).toHaveValue('');
      expect(submitButton()).toBeDisabled();
    });

    it('forgets a rejection as well as a success', async () => {
      const { harness, user } = renderDialog();
      harness.createResponses.push(
        apiError(400, 'TASK_DUE_JOURNAL_NOT_FUTURE', NOT_FUTURE_DETAIL)
      );

      await open(user);
      await fillAndSubmit(user);
      await screen.findByText(NOT_FUTURE_DETAIL);
      await user.click(screen.getByTestId('create-task-dialog-cancel'));

      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      await open(user);
      expect(screen.queryByText(NOT_FUTURE_DETAIL)).toBeNull();
    });

    /**
     * The request has already left and may have committed, so a dialog that
     * vanished on Cancel and then toasted "Task created" would be reporting
     * the opposite of what the user had just asked for.
     */
    it('refuses to close while the write is in flight', async () => {
      const held = heldResponse();
      const { harness, user } = renderDialog();
      harness.createResponses.push(held.response);

      await open(user);
      await fillAndSubmit(user);

      expect(screen.getByTestId('create-task-dialog-cancel')).toBeDisabled();
      await user.keyboard('{Escape}');
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      // Radix's own close button asks for the same close this refuses, so it
      // is withdrawn rather than left sitting there doing nothing.
      expect(screen.queryByRole('button', { name: /close/i })).toBeNull();

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('locks its fields while the write is in flight', async () => {
      const held = heldResponse();
      const { harness, user } = renderDialog();
      harness.createResponses.push(held.response);

      await open(user);
      await fillAndSubmit(user);

      expect(screen.getByTestId('create-task-text')).toBeDisabled();
      expect(screen.getByTestId('future-journal-search')).toBeDisabled();
      expect(contactSearch()).toBeDisabled();
      expect(submitButton()).toBeDisabled();

      held.release();
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    /**
     * Stated rather than left to Radix's "first tabbable node", which a
     * control added above the text field later would change silently.
     */
    it('opens with the cursor in the text field', async () => {
      const { user } = renderDialog();

      await open(user);

      expect(screen.getByTestId('create-task-text')).toHaveFocus();
    });
  });
});
