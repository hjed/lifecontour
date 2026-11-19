/**
 * @jest-environment jsdom
 */

/**
 * The create-task form when the **creating** journal is a choice.
 *
 * On the journal page the creating journal is the journal being viewed and is
 * never offered (`fixed`, pinned by `CreateTaskDialog.test.tsx`). The New
 * dialog has no journal around it, so the specification has it ask: "the
 * dialog asks for the creating journal and the future due journal", pre-filled
 * with the journal being viewed, "otherwise the user must choose" (`choose`).
 *
 * The refusal for an unreachable anchor names which anchor as `meta.anchor`,
 * and these tests pin where each one lands in both modes.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { toast } from 'sonner';

import { CreateTaskForm, type CreatingJournalSource } from '../CreateTaskForm';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { addDaysToIsoDate, todayIn } from '@/lib/future-journals';
import { JournalType } from '@/types/journals';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// `jest.setup.ts` trims `@/lib/constants` to the auth endpoints.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const DUE_JOURNAL = 42;
const SEARCHED_JOURNAL = { id: '5', title: 'Trip planning' };
const PRESET_JOURNAL = { id: '3', title: 'Committee meeting' };

const ok = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
  }) as unknown as Response;

const dueJournalDate = addDaysToIsoDate(todayIn('UTC'), 3);

function journalResource(id: string, title: string, date: string) {
  return {
    id,
    type: 'journals',
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

const FUTURE_LISTING = {
  data: [journalResource(String(DUE_JOURNAL), 'Weekly review', dueJournalDate)],
  meta: { total: 1 },
};

const SEARCH_RESULTS = {
  data: [
    journalResource(SEARCHED_JOURNAL.id, SEARCHED_JOURNAL.title, '2026-01-04'),
  ],
  meta: { total: 1, page: 1, size: 20, pages: 1 },
};

const CREATED = {
  data: {
    type: 'tasks',
    id: '99',
    attributes: {
      text: 'Print the permit',
      status: 'not_done',
      creating_journal_id: 5,
      due_journal_id: DUE_JOURNAL,
      intermediate_journal_ids: [],
    },
  },
};

const anchorRefusal = (anchor: 'creating' | 'due') =>
  ok(404, {
    errors: [
      {
        status: '404',
        code: 'TASK_ANCHOR_JOURNAL_NOT_FOUND',
        detail: `The ${anchor} journal (ID 5) was not found. A task must be anchored to journals that exist and belong to you.`,
        meta: { anchor },
      },
    ],
  });

function setup(
  creatingJournal: CreatingJournalSource,
  createResponse: Response = ok(201, CREATED)
) {
  const posts: string[] = [];

  mockFetch.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/api/user-settings')) {
      return ok(200, { data: { attributes: { timezone: 'UTC' } } });
    }
    if (init?.method === 'POST') {
      posts.push(url);
      return createResponse;
    }
    if (url.includes('search=')) return ok(200, SEARCH_RESULTS);
    if (url.includes('/api/journals')) return ok(200, FUTURE_LISTING);
    throw new Error(`unexpected request: ${url}`);
  });

  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <CreateTaskForm
        creatingJournal={creatingJournal}
        onCreated={jest.fn()}
        onCancel={jest.fn()}
      />
    </QueryClientProvider>
  );

  return { user: userEvent.setup(), posts };
}

const creatingField = () =>
  screen.getByRole('combobox', { name: 'Journal this task arose in' });

/** The text of every element an input's `aria-describedby` names. */
function description(input: HTMLElement): string {
  return (input.getAttribute('aria-describedby') ?? '')
    .split(' ')
    .filter(Boolean)
    .map(id => document.getElementById(id)?.textContent ?? '')
    .join(' ');
}

async function fillTextAndDue(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByTestId('create-task-text'), 'Print the permit');
  await user.click(
    await screen.findByTestId(`future-journal-option-${DUE_JOURNAL}`)
  );
}

async function chooseSearchedJournal(user: ReturnType<typeof userEvent.setup>) {
  await user.type(creatingField(), 'Trip');
  const option = await screen.findByRole('option', {
    name: new RegExp(SEARCHED_JOURNAL.title),
  });
  await user.click(within(option).getByRole('button'));
}

const submit = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByTestId('create-task-dialog-submit'));

describe('CreateTaskForm — choosing the creating journal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('asks for the creating journal and offers no date field', () => {
    setup({ kind: 'choose' });

    expect(creatingField()).toBeInTheDocument();
    expect(document.querySelector('input[type="date"]')).toBeNull();
  });

  it('refuses to send without a creating journal, saying so on the field', async () => {
    const { user, posts } = setup({ kind: 'choose' });

    await fillTextAndDue(user);
    await submit(user);

    const field = creatingField();
    await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'));
    expect(description(field)).toContain(
      'Choose the journal this task arose in.'
    );
    // `FormMessage` is not a live region: moving into the described input is
    // how a screen-reader user hears why Create did nothing.
    expect(field).toHaveFocus();
    expect(posts).toHaveLength(0);
  });

  it('creates the task in a journal chosen by search', async () => {
    const { user, posts } = setup({ kind: 'choose' });

    await chooseSearchedJournal(user);
    expect(creatingField()).toHaveValue(SEARCHED_JOURNAL.title);
    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(
      new RegExp(`/api/journals/${SEARCHED_JOURNAL.id}/tasks$`)
    );
  });

  it('starts from the journal it is given, and sends to it', async () => {
    const { user, posts } = setup({ kind: 'choose', initial: PRESET_JOURNAL });

    expect(creatingField()).toHaveValue(PRESET_JOURNAL.title);
    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(
      new RegExp(`/api/journals/${PRESET_JOURNAL.id}/tasks$`)
    );
  });

  it('lets a different journal replace the one it started from', async () => {
    const { user, posts } = setup({ kind: 'choose', initial: PRESET_JOURNAL });

    await user.clear(creatingField());
    await chooseSearchedJournal(user);
    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(
      new RegExp(`/api/journals/${SEARCHED_JOURNAL.id}/tasks$`)
    );
  });

  it('forgets the chosen journal once its name is typed over', async () => {
    const { user, posts } = setup({ kind: 'choose', initial: PRESET_JOURNAL });

    await user.type(creatingField(), 'x');
    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() =>
      expect(creatingField()).toHaveAttribute('aria-invalid', 'true')
    );
    expect(posts).toHaveLength(0);
  });

  it('chooses the journal again when its title is typed back in', async () => {
    const { user, posts } = setup({ kind: 'choose', initial: PRESET_JOURNAL });

    await user.type(creatingField(), 'x');
    await user.type(creatingField(), '{Backspace}');
    expect(creatingField()).toHaveValue(PRESET_JOURNAL.title);
    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(
      new RegExp(`/api/journals/${PRESET_JOURNAL.id}/tasks$`)
    );
  });

  it('puts an unreachable creating journal on its field and moves focus there', async () => {
    const { user } = setup(
      { kind: 'choose', initial: PRESET_JOURNAL },
      anchorRefusal('creating')
    );

    await fillTextAndDue(user);
    await submit(user);

    const field = creatingField();
    await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'));
    expect(description(field)).toContain('The creating journal (ID 5)');
    expect(field).toHaveFocus();
    // Kept, for a user who has scrolled away from the field.
    expect(toast.error).toHaveBeenCalled();
  });

  it('puts an unreachable due journal on the due field', async () => {
    const { user } = setup(
      { kind: 'choose', initial: PRESET_JOURNAL },
      anchorRefusal('due')
    );

    await fillTextAndDue(user);
    await submit(user);

    expect(
      await screen.findByText(/The due journal \(ID 5\)/)
    ).toBeInTheDocument();
    expect(creatingField()).not.toHaveAttribute('aria-invalid', 'true');
  });
});

describe('CreateTaskForm — the creating journal fixed by its host', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('offers no creating-journal field', () => {
    setup({ kind: 'fixed', id: '7' });

    expect(
      screen.queryByRole('combobox', { name: 'Journal this task arose in' })
    ).toBeNull();
  });

  it('leaves an unreachable creating journal to the toast, having no field for it', async () => {
    const { user } = setup(
      { kind: 'fixed', id: '7' },
      anchorRefusal('creating')
    );

    await fillTextAndDue(user);
    await submit(user);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByText(/The creating journal \(ID 5\)/)).toBeNull();
  });

  it('puts an unreachable due journal on the due field', async () => {
    const { user } = setup({ kind: 'fixed', id: '7' }, anchorRefusal('due'));

    await fillTextAndDue(user);
    await submit(user);

    expect(
      await screen.findByText(/The due journal \(ID 5\)/)
    ).toBeInTheDocument();
  });
});
