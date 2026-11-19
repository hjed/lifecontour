/**
 * @jest-environment jsdom
 */

/**
 * Tests for the create-task form on its own, outside any dialog.
 *
 * The rules the form keeps — the request's shape, the due-journal picker,
 * contacts, refusals landing on their fields — are pinned through its first
 * host by `CreateTaskDialog.test.tsx`. This suite covers only what a host
 * relies on: that the form works with no dialog around it, and when it calls
 * `onCreated`, `onCancel` and `onBusyChange`.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';

import { CreateTaskForm } from '../CreateTaskForm';
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

const CREATING_JOURNAL = '7';
const DUE_JOURNAL = 42;

const ok = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
  }) as unknown as Response;

const dueJournalDate = addDaysToIsoDate(todayIn('UTC'), 3);
const LISTING = {
  data: [
    {
      id: String(DUE_JOURNAL),
      type: 'journals',
      attributes: {
        title: 'Weekly review',
        content: '',
        event_date_range: {
          start: `${dueJournalDate}T12:00:00Z`,
          end: `${dueJournalDate}T13:00:00Z`,
        },
        types: [JournalType.NOTE],
        contacts: [],
        tags: [],
      },
    },
  ],
  meta: { total: 1 },
};

const CREATED = {
  data: {
    type: 'tasks',
    id: '99',
    attributes: {
      text: 'Print the permit',
      status: 'not_done',
      creating_journal_id: Number(CREATING_JOURNAL),
      due_journal_id: DUE_JOURNAL,
      intermediate_journal_ids: [],
    },
  },
};

interface Setup {
  /** What the create endpoint answers; a 201 unless a test says otherwise. */
  readonly createResponse?: Promise<Response> | Response;
  readonly autoFocusText?: boolean;
}

function setup({ createResponse, autoFocusText }: Setup = {}) {
  const onCreated = jest.fn<void, []>();
  const onCancel = jest.fn<void, []>();
  const onBusyChange = jest.fn<void, [boolean]>();
  const posts: string[] = [];
  /** `onBusyChange` calls made by the time the request left. */
  const busyCallsAtPost: boolean[][] = [];

  mockFetch.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/api/user-settings')) {
      return ok(200, { data: { attributes: { timezone: 'UTC' } } });
    }
    if (init?.method === 'POST') {
      posts.push(url);
      busyCallsAtPost.push(onBusyChange.mock.calls.map(([busy]) => busy));
      return createResponse ?? ok(201, CREATED);
    }
    if (url.includes('/api/journals')) return ok(200, LISTING);
    throw new Error(`unexpected request: ${url}`);
  });

  const view = render(
    <QueryClientProvider client={createTestQueryClient()}>
      <button type='button'>elsewhere</button>
      <CreateTaskForm
        creatingJournal={{ kind: 'fixed', id: CREATING_JOURNAL }}
        onCreated={onCreated}
        onCancel={onCancel}
        onBusyChange={onBusyChange}
        {...(autoFocusText ? { autoFocusText } : {})}
      />
    </QueryClientProvider>
  );

  return {
    ...view,
    user: userEvent.setup(),
    onCreated,
    onCancel,
    onBusyChange,
    posts,
    busyCallsAtPost,
  };
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByTestId('create-task-text'), 'Print the permit');
  await user.click(
    await screen.findByTestId(`future-journal-option-${DUE_JOURNAL}`)
  );
  await user.click(screen.getByTestId('create-task-dialog-submit'));
}

/** A create response the test releases when it chooses. */
function held() {
  let release: (response: Response) => void = () => undefined;
  const response = new Promise<Response>(resolve => {
    release = resolve;
  });
  return { response, release };
}

describe('CreateTaskForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('creates the task in the given journal with no dialog around it', async () => {
    const { user, posts } = setup();

    expect(screen.queryByRole('dialog')).toBeNull();
    await fillAndSubmit(user);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(
      new RegExp(`/api/journals/${CREATING_JOURNAL}/tasks$`)
    );
  });

  it('tells its host once the task exists', async () => {
    const { user, onCreated } = setup();

    await fillAndSubmit(user);

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  });

  it('does not report a refused create as created', async () => {
    const { user, onCreated, onBusyChange } = setup({
      createResponse: ok(422, {
        errors: [{ status: '422', code: 'SOMETHING_ELSE', detail: 'No.' }],
      }),
    });

    await fillAndSubmit(user);

    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('hands Cancel to its host and writes nothing', async () => {
    const { user, onCancel, posts } = setup();

    await user.click(screen.getByTestId('create-task-dialog-cancel'));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(posts).toHaveLength(0);
  });

  /**
   * Reported before the request leaves, not on the render after: a host that
   * refuses to close while busy would otherwise have a moment in which it
   * closes over a write that is already on its way.
   */
  it('reports busy as the request leaves and idle once it settles', async () => {
    const create = held();
    const { user, onBusyChange, busyCallsAtPost } = setup({
      createResponse: create.response,
    });

    await fillAndSubmit(user);

    await waitFor(() => expect(busyCallsAtPost).toHaveLength(1));
    expect(busyCallsAtPost[0]).toContain(true);
    expect(onBusyChange).toHaveBeenLastCalledWith(true);

    create.release(ok(201, CREATED));
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
  });

  /**
   * The New dialog can be closed under a running save. The task still gets
   * made, but a form that has gone must not reach for a host that may now be
   * showing something else.
   */
  it('stays quiet about a create that settles after it has gone', async () => {
    const create = held();
    const { user, onCreated, onBusyChange, unmount } = setup({
      createResponse: create.response,
    });

    await fillAndSubmit(user);
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(true));

    unmount();
    expect(onBusyChange).toHaveBeenLastCalledWith(false);

    create.release(ok(201, CREATED));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('leaves focus where it was unless asked to take it', () => {
    setup();

    expect(screen.getByTestId('create-task-text')).not.toHaveFocus();
  });

  it('puts the cursor in the text field when asked to', () => {
    setup({ autoFocusText: true });

    expect(screen.getByTestId('create-task-text')).toHaveFocus();
  });
});
