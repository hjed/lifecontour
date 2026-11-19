/**
 * @jest-environment jsdom
 */

/**
 * The New dialog's Task panel: a task in a journal.
 *
 * The form's own rules are `CreateTaskForm`'s tests. This suite pins what the
 * panel adds — the creating journal pre-filled with "the journal being
 * viewed", and nothing pre-filled anywhere else — and the props the dialog
 * hands every panel.
 */

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';

import { NewTaskPanel } from '../NewTaskPanel';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { addDaysToIsoDate, todayIn } from '@/lib/future-journals';
import { JournalType } from '@/types/journals';

globalThis.fetch = jest.fn();
const mockFetch = globalThis.fetch as jest.MockedFunction<typeof fetch>;

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

let mockPathname = '/';
jest.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
}));

const VIEWED = { id: '7', title: 'Trip planning' };
const SEARCHED = { id: '5', title: 'Hut booking' };
const DUE_JOURNAL = 42;

const ok = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
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

interface Setup {
  readonly pathname: string;
  /** What the viewed journal's read answers; immediate unless held. */
  readonly journalRead?: Promise<Response>;
  readonly shownOnOpen?: boolean;
}

function setup({ pathname, journalRead, shownOnOpen = false }: Setup) {
  mockPathname = pathname;
  const posts: string[] = [];
  const onCreated = jest.fn<void, []>();
  const onBusyChange = jest.fn<void, [boolean]>();

  mockFetch.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/api/user-settings')) {
      return ok(200, { data: { attributes: { timezone: 'UTC' } } });
    }
    if (init?.method === 'POST') {
      posts.push(url);
      return ok(201, {
        data: { type: 'tasks', id: '99', attributes: { text: 'x' } },
      });
    }
    if (url.endsWith(`/api/journals/${VIEWED.id}`)) {
      return (
        journalRead ??
        ok(200, {
          data: journalResource(VIEWED.id, VIEWED.title, '2026-01-02'),
        })
      );
    }
    if (url.includes('search=')) {
      return ok(200, {
        data: [journalResource(SEARCHED.id, SEARCHED.title, '2026-01-03')],
        meta: { total: 1, page: 1, size: 20, pages: 1 },
      });
    }
    if (url.includes('/api/journals')) {
      return ok(200, {
        data: [
          journalResource(String(DUE_JOURNAL), 'Weekly review', dueJournalDate),
        ],
        meta: { total: 1 },
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });

  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <NewTaskPanel
        onCreated={onCreated}
        onCancel={jest.fn()}
        onBusyChange={onBusyChange}
        shownOnOpen={shownOnOpen}
      />
    </QueryClientProvider>
  );

  return { user: userEvent.setup(), posts, onCreated, onBusyChange };
}

const creatingField = () =>
  screen.getByRole('combobox', { name: 'Journal this task arose in' });

async function fillTextAndDue(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByTestId('create-task-text'), 'Print the permit');
  await user.click(
    await screen.findByTestId(`future-journal-option-${DUE_JOURNAL}`)
  );
}

/**
 * Let a released journal read reach the panel: the response body, the query
 * cache and the re-render each take a turn of the event loop.
 */
async function settleViewedRead() {
  await act(() => new Promise(resolve => setTimeout(resolve, 100)));
}

describe('NewTaskPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('pre-fills the journal being viewed as the creating journal', async () => {
    const { user, posts } = setup({ pathname: `/journals/${VIEWED.id}` });

    await waitFor(() => expect(creatingField()).toHaveValue(VIEWED.title));
    await fillTextAndDue(user);
    await user.click(screen.getByTestId('create-task-dialog-submit'));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatch(new RegExp(`/api/journals/${VIEWED.id}/tasks$`));
  });

  it('does not overwrite a journal the user chose before the viewed one loaded', async () => {
    let release: (response: Response) => void = () => undefined;
    const journalRead = new Promise<Response>(resolve => {
      release = resolve;
    });
    const { user } = setup({ pathname: `/journals/${VIEWED.id}`, journalRead });

    await user.type(creatingField(), 'Hut');
    const option = await screen.findByRole('option', {
      name: new RegExp(SEARCHED.title),
    });
    await user.click(within(option).getByRole('button'));
    expect(creatingField()).toHaveValue(SEARCHED.title);

    release(
      ok(200, { data: journalResource(VIEWED.id, VIEWED.title, '2026-01-02') })
    );
    await settleViewedRead();

    expect(creatingField()).toHaveValue(SEARCHED.title);
  });

  it('does not overwrite what the user typed before the viewed one loaded', async () => {
    let release: (response: Response) => void = () => undefined;
    const journalRead = new Promise<Response>(resolve => {
      release = resolve;
    });
    const { user } = setup({ pathname: `/journals/${VIEWED.id}`, journalRead });

    await user.type(creatingField(), 'Hu');
    release(
      ok(200, { data: journalResource(VIEWED.id, VIEWED.title, '2026-01-02') })
    );
    await settleViewedRead();

    expect(creatingField()).toHaveValue('Hu');
  });

  it('pre-fills nothing away from a journal page, leaving the choice to the user', async () => {
    const { user, posts } = setup({ pathname: '/contacts' });

    expect(creatingField()).toHaveValue('');
    await fillTextAndDue(user);
    await user.click(screen.getByTestId('create-task-dialog-submit'));

    await waitFor(() =>
      expect(creatingField()).toHaveAttribute('aria-invalid', 'true')
    );
    expect(posts).toHaveLength(0);
  });

  it('takes focus only when it is the panel shown on open', () => {
    setup({ pathname: '/contacts', shownOnOpen: true });

    expect(screen.getByTestId('create-task-text')).toHaveFocus();
  });

  it('leaves focus alone when it is not', () => {
    setup({ pathname: '/contacts' });

    expect(screen.getByTestId('create-task-text')).not.toHaveFocus();
  });

  it('tells the dialog the task exists, and reports its save', async () => {
    const { user, onCreated, onBusyChange } = setup({
      pathname: `/journals/${VIEWED.id}`,
    });

    await waitFor(() => expect(creatingField()).toHaveValue(VIEWED.title));
    await fillTextAndDue(user);
    await user.click(screen.getByTestId('create-task-dialog-submit'));

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onBusyChange).toHaveBeenCalledWith(true);
  });
});
