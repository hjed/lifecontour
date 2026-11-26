/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { useTaskListOpenTasks } from '@/lib/api/list-tasks';
import { taskKeys } from '@/lib/api/tasks';
import { mockApiResponse } from '@/test-utils';
import { createMockListTaskRead } from '@/test-utils/tasks';
import {
  TaskStatus,
  isListTask,
  type ListTaskReadResource,
  type ListTasksResponse,
} from '@/types/tasks';
import { TaskStatusCheckbox } from '../TaskStatusCheckbox';

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const LIST_ID = '7';

function OpenTasks() {
  const { data } = useTaskListOpenTasks(LIST_ID);
  return (
    <ul>
      {data?.data.filter(isListTask).map(task => (
        <li key={task.id}>
          <TaskStatusCheckbox task={task} />
        </li>
      ))}
    </ul>
  );
}

function renderWithCachedTask(task: ListTaskReadResource): QueryClient {
  const queryClient = createTestQueryClient();
  const cached: ListTasksResponse = { data: [task], meta: { total: 1 } };
  queryClient.setQueryData(taskKeys.openOnList(LIST_ID), cached);
  render(
    <QueryClientProvider client={queryClient}>
      <OpenTasks />
    </QueryClientProvider>
  );
  return queryClient;
}

function patchBodies(fetchMock: jest.Mock): unknown[] {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === 'PATCH')
    .map(([, init]) => JSON.parse(String(init.body)));
}

function neverAnswers(): Promise<Response> {
  return new Promise(() => undefined);
}

describe('TaskStatusCheckbox', () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn();
    globalThis.fetch = fetchMock;
  });

  it('marks an open task done', async () => {
    const task = createMockListTaskRead({ id: '42', text: 'Pack the tent' });
    fetchMock.mockImplementation(neverAnswers);
    renderWithCachedTask(task);

    await userEvent.click(
      screen.getByRole('checkbox', { name: 'Done: Pack the tent' })
    );

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/tasks/42',
      expect.objectContaining({ method: 'PATCH' })
    );
    expect(patchBodies(fetchMock)).toEqual([
      { data: { type: 'tasks', id: '42', attributes: { status: 'done' } } },
    ]);
  });

  it.each([TaskStatus.DONE, TaskStatus.CANCELLED])(
    'reopens a %s task directly, without a reopen acknowledgement',
    async status => {
      const task = createMockListTaskRead({ id: '42', status });
      fetchMock.mockImplementation(neverAnswers);
      renderWithCachedTask(task);

      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).toBeChecked();
      await userEvent.click(checkbox);

      expect(patchBodies(fetchMock)).toEqual([
        {
          data: {
            type: 'tasks',
            id: '42',
            attributes: { status: 'not_done' },
          },
        },
      ]);
    }
  );

  it('shows the tick at once, from the cached task', async () => {
    fetchMock.mockImplementation(neverAnswers);
    renderWithCachedTask(createMockListTaskRead());

    const checkbox = screen.getByRole('checkbox');
    await userEvent.click(checkbox);

    expect(checkbox).toBeChecked();
  });

  it('holds further toggles while its write is in flight', async () => {
    fetchMock.mockImplementation(neverAnswers);
    renderWithCachedTask(createMockListTaskRead());

    const checkbox = screen.getByRole('checkbox');
    await userEvent.click(checkbox);

    expect(checkbox).toHaveAttribute('aria-busy', 'true');
    expect(checkbox).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(checkbox);
    expect(patchBodies(fetchMock)).toHaveLength(1);
    expect(checkbox).toBeChecked();
  });

  it('is not busy while nothing is being written', () => {
    renderWithCachedTask(createMockListTaskRead());

    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toHaveAttribute('aria-busy', 'false');
    expect(checkbox).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('takes back the tick when the write is refused', async () => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === 'PATCH'
        ? mockApiResponse(
            {
              errors: [
                { status: '404', code: 'TASK_NOT_FOUND', detail: 'Gone' },
              ],
            },
            { status: 404 }
          )
        : neverAnswers()
    );
    renderWithCachedTask(createMockListTaskRead());

    const checkbox = screen.getByRole('checkbox');
    await userEvent.click(checkbox);

    await waitFor(() => expect(checkbox).not.toBeChecked());
    expect(patchBodies(fetchMock)).toHaveLength(1);
  });

  it('is described by the element it is given', () => {
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <span id='why'>Cancelled</span>
        <TaskStatusCheckbox
          task={createMockListTaskRead({ status: TaskStatus.CANCELLED })}
          describedById='why'
        />
      </QueryClientProvider>
    );

    expect(screen.getByRole('checkbox')).toHaveAccessibleDescription(
      'Cancelled'
    );
  });
});
