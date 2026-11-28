/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createTestQueryClient } from '@/components/journals/test-helpers';
import { createMockListTaskRead } from '@/test-utils/tasks';
import type { ListTaskReadResource } from '@/types/tasks';
import { TaskListOpenTasks } from '../TaskListOpenTasks';

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const A = createMockListTaskRead({ id: '1', text: 'Pack the tent' });
const B = createMockListTaskRead({ id: '2', text: 'Buy fuel' });
const C = createMockListTaskRead({ id: '3', text: 'Charge the torch' });
const D = createMockListTaskRead({ id: '4', text: 'Fill the water bottles' });
const E = createMockListTaskRead({ id: '5', text: 'Print the map' });

function renderOpenTasks(tasks: readonly ListTaskReadResource[]) {
  const client = createTestQueryClient();
  const view = render(
    <QueryClientProvider client={client}>
      <TaskListOpenTasks tasks={tasks} />
    </QueryClientProvider>
  );
  const rerender = (next: readonly ListTaskReadResource[]) =>
    view.rerender(
      <QueryClientProvider client={client}>
        <TaskListOpenTasks tasks={next} />
      </QueryClientProvider>
    );
  return { rerender };
}

const checkbox = (text: string) =>
  screen.getByRole('checkbox', { name: `Done: ${text}` });

describe('TaskListOpenTasks', () => {
  it('lists the tasks in the order given, in a region named Open tasks', () => {
    renderOpenTasks([C, A, B]);

    const region = screen.getByRole('region', { name: 'Open tasks' });
    const rows = within(within(region).getByRole('list')).getAllByRole(
      'listitem'
    );
    expect(rows.map(row => row.dataset.testid)).toEqual([
      'task-row-3',
      'task-row-1',
      'task-row-2',
    ]);
  });

  it('says the list has no open tasks, and draws no list, when it is empty', () => {
    renderOpenTasks([]);

    const region = screen.getByRole('region', { name: 'Open tasks' });
    expect(
      within(region).getByText('No open tasks on this list')
    ).toBeInTheDocument();
    expect(
      within(region).getByText('Tasks you add to this list will appear here.')
    ).toBeInTheDocument();
    expect(within(region).queryByRole('list')).not.toBeInTheDocument();
  });

  describe('when the focused task leaves the list', () => {
    it('moves focus to the task that took its place', () => {
      const { rerender } = renderOpenTasks([A, B, C]);
      checkbox('Buy fuel').focus();

      rerender([A, C]);

      expect(checkbox('Charge the torch')).toHaveFocus();
    });

    it('moves focus to the next task still there when one above left too', () => {
      const { rerender } = renderOpenTasks([A, B, C, D, E]);
      checkbox('Charge the torch').focus();

      rerender([B, D, E]);

      expect(checkbox('Fill the water bottles')).toHaveFocus();
    });

    it('moves focus to the new last task when the last one left', () => {
      const { rerender } = renderOpenTasks([A, B, C]);
      checkbox('Charge the torch').focus();

      rerender([A, B]);

      expect(checkbox('Buy fuel')).toHaveFocus();
    });

    it('moves focus to the Open tasks heading when no task is left', () => {
      const { rerender } = renderOpenTasks([B]);
      checkbox('Buy fuel').focus();

      rerender([]);

      expect(screen.getByRole('heading', { name: 'Open tasks' })).toHaveFocus();
    });

    it('takes no focus back once the user has left the list', () => {
      const outside = document.createElement('button');
      document.body.append(outside);
      const { rerender } = renderOpenTasks([A, B, C]);
      checkbox('Buy fuel').focus();
      outside.focus();
      outside.blur();

      rerender([A, C]);

      expect(document.body).toHaveFocus();
      outside.remove();
    });

    it('takes no focus back once the user has clicked away to the page', () => {
      const { rerender } = renderOpenTasks([A, B, C]);
      checkbox('Buy fuel').focus();
      checkbox('Buy fuel').blur();

      rerender([A, C]);

      expect(document.body).toHaveFocus();
    });

    it('leaves focus alone when it had already moved elsewhere', () => {
      const { rerender } = renderOpenTasks([A, B, C]);
      checkbox('Buy fuel').focus();
      checkbox('Pack the tent').focus();

      rerender([A, C]);

      expect(checkbox('Pack the tent')).toHaveFocus();
    });
  });
});
