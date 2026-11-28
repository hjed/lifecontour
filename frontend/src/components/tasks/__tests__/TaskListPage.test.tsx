/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { mockApiResponse } from '@/test-utils';
import { taskListKeys } from '@/lib/api/task-list-keys';
import { taskKeys } from '@/lib/api/tasks';
import { createMockListTaskRead } from '@/test-utils/tasks';
import type { TaskListResponse } from '@/types/task-lists';
import {
  TaskStatus,
  type ListTaskReadResource,
  type ListTasksResponse,
} from '@/types/tasks';
import { TaskListPage } from '../TaskListPage';

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const HOUSE: TaskListResponse = {
  data: {
    type: 'task-lists',
    id: '7',
    attributes: {
      name: 'House',
      icon: 'house',
      position: 0,
      archived: false,
      archived_at: null,
      associated_journal_id: null,
      created_at: '2026-11-20T00:00:00Z',
      updated_at: '2026-11-20T00:00:00Z',
    },
  },
};

const GUTTERS = createMockListTaskRead({ id: '1', text: 'Clean the gutters' });
const PLUMBER = createMockListTaskRead({ id: '2', text: 'Book the plumber' });

function openTasks(...tasks: ListTaskReadResource[]): ListTasksResponse {
  return { data: tasks, meta: { total: tasks.length } };
}

function notFound(): Response {
  return mockApiResponse(
    {
      errors: [
        {
          status: '404',
          code: 'TASK_LIST_NOT_FOUND',
          detail: 'Task list not found',
        },
      ],
    },
    { status: 404 }
  );
}

interface Answers {
  readonly list: () => Response;
  readonly openTasks: () => Response;
  readonly patch?: () => Promise<Response>;
}

function serverError(): Response {
  return mockApiResponse(
    { errors: [{ status: '500', detail: 'Boom' }] },
    { status: 500 }
  );
}

function answerWith(answers: Answers): jest.Mock {
  const fetchMock = jest.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'PATCH') {
      return answers.patch?.() ?? Promise.resolve(mockApiResponse({}));
    }
    if (url === '/api/task-lists/7') return Promise.resolve(answers.list());
    if (url === '/api/task-lists/7/tasks') {
      return Promise.resolve(answers.openTasks());
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

/**
 * The list reads retry a server failure whatever the client's default, so the
 * test client spends no time between attempts.
 */
function renderPage(rawId = '7'): QueryClient {
  const queryClient = createTestQueryClient();
  queryClient.setDefaultOptions({
    ...queryClient.getDefaultOptions(),
    queries: { ...queryClient.getDefaultOptions().queries, retryDelay: 0 },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TaskListPage rawId={rawId} />
    </QueryClientProvider>
  );
  return queryClient;
}

describe('TaskListPage', () => {
  it('holds a loading skeleton until the list and its tasks arrive', async () => {
    answerWith({
      list: () => mockApiResponse(HOUSE),
      openTasks: () => mockApiResponse(openTasks(GUTTERS)),
    });

    renderPage();

    expect(
      screen.getByRole('status', { name: 'Loading list' })
    ).toHaveAttribute('aria-busy', 'true');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'House' })
    ).toBeInTheDocument();
    expect(screen.queryByTestId('task-list-loading')).not.toBeInTheDocument();
  });

  it('shows the breadcrumb, header and open tasks in order', async () => {
    answerWith({
      list: () => mockApiResponse(HOUSE),
      openTasks: () => mockApiResponse(openTasks(PLUMBER, GUTTERS)),
    });

    renderPage();

    const nav = await screen.findByRole('navigation', { name: 'Breadcrumb' });
    expect(within(nav).getByText('House')).toHaveAttribute(
      'aria-current',
      'page'
    );
    expect(screen.getByTestId('task-list-summary')).toHaveTextContent('2 open');
    const region = screen.getByRole('region', { name: 'Open tasks' });
    expect(
      within(region)
        .getAllByRole('checkbox')
        .map(box => box.getAttribute('aria-label'))
    ).toEqual(['Done: Book the plumber', 'Done: Clean the gutters']);
  });

  it('says the list is not found for an id that cannot be one, without asking', () => {
    const fetchMock = answerWith({
      list: () => mockApiResponse(HOUSE),
      openTasks: () => mockApiResponse(openTasks()),
    });

    renderPage('abc');

    expect(
      screen.getByRole('heading', { level: 1, name: 'List not found' })
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go home' })).toHaveAttribute(
      'href',
      '/'
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('says the list is not found when the server refuses it', async () => {
    answerWith({ list: notFound, openTasks: notFound });

    renderPage();

    expect(
      await screen.findByRole('heading', { level: 1, name: 'List not found' })
    ).toBeInTheDocument();
  });

  it('says the list is not found when only its tasks are refused', async () => {
    answerWith({ list: () => mockApiResponse(HOUSE), openTasks: notFound });

    renderPage();

    expect(
      await screen.findByRole('heading', { level: 1, name: 'List not found' })
    ).toBeInTheDocument();
  });

  it('says the list is not found once it is deleted while open', async () => {
    let gone = false;
    answerWith({
      list: () => (gone ? notFound() : mockApiResponse(HOUSE)),
      openTasks: () => (gone ? notFound() : mockApiResponse(openTasks())),
    });
    const queryClient = renderPage();
    await screen.findByRole('heading', { level: 1, name: 'House' });

    gone = true;
    await queryClient.invalidateQueries({ queryKey: taskListKeys.detail('7') });

    expect(
      await screen.findByRole('heading', { level: 1, name: 'List not found' })
    ).toBeInTheDocument();
  });

  it('keeps showing the list when a refetch fails for another reason', async () => {
    let failing = false;
    answerWith({
      list: () => (failing ? serverError() : mockApiResponse(HOUSE)),
      openTasks: () =>
        failing ? serverError() : mockApiResponse(openTasks(GUTTERS)),
    });
    const queryClient = renderPage();
    await screen.findByRole('heading', { level: 1, name: 'House' });

    failing = true;
    await queryClient.invalidateQueries({ queryKey: taskKeys.openOnList('7') });

    await waitFor(() =>
      expect(queryClient.getQueryState(taskKeys.openOnList('7'))?.status).toBe(
        'error'
      )
    );
    expect(
      screen.getByRole('checkbox', { name: 'Done: Clean the gutters' })
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reports any other failure once its retries are spent', async () => {
    const fetchMock = answerWith({
      list: serverError,
      openTasks: () => mockApiResponse(openTasks()),
    });

    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't load this list"
    );
    expect(screen.queryByText('List not found')).not.toBeInTheDocument();
    const listReads = fetchMock.mock.calls.filter(
      ([url]) => url === '/api/task-lists/7'
    );
    expect(listReads).toHaveLength(4);
  });

  it('completes a task in place: the count drops at once and the row leaves on refetch', async () => {
    let tasksAnswer = openTasks(PLUMBER, GUTTERS);
    let answerPatch: () => void = () => undefined;
    answerWith({
      list: () => mockApiResponse(HOUSE),
      openTasks: () => mockApiResponse(tasksAnswer),
      patch: () =>
        new Promise<Response>(resolve => {
          answerPatch = () => {
            tasksAnswer = openTasks(GUTTERS);
            resolve(
              mockApiResponse({
                data: {
                  ...PLUMBER,
                  attributes: {
                    ...PLUMBER.attributes,
                    status: TaskStatus.DONE,
                  },
                },
              })
            );
          };
        }),
    });
    renderPage();
    const checkbox = await screen.findByRole('checkbox', {
      name: 'Done: Book the plumber',
    });

    await userEvent.click(checkbox);

    expect(checkbox).toBeChecked();
    expect(screen.getByTestId('task-list-summary')).toHaveTextContent('1 open');

    answerPatch();

    await waitFor(() =>
      expect(
        screen.queryByRole('checkbox', { name: 'Done: Book the plumber' })
      ).not.toBeInTheDocument()
    );
    expect(
      screen.getByRole('checkbox', { name: 'Done: Clean the gutters' })
    ).toBeInTheDocument();
  });
});
