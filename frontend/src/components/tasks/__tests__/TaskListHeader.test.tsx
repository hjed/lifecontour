/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { createMockListTaskRead } from '@/test-utils/tasks';
import { TaskListHeader } from '../TaskListHeader';

describe('TaskListHeader', () => {
  it("shows the list's name as the page heading", () => {
    render(<TaskListHeader name='House' icon={null} tasks={[]} />);

    expect(
      screen.getByRole('heading', { level: 1, name: 'House' })
    ).toBeInTheDocument();
  });

  it('shows how many tasks are open and overdue', () => {
    const tasks = [
      createMockListTaskRead({ id: '1', overdue: true }),
      createMockListTaskRead({ id: '2' }),
    ];

    render(<TaskListHeader name='House' icon={null} tasks={tasks} />);

    expect(screen.getByTestId('task-list-summary')).toHaveTextContent(
      '2 open · 1 overdue'
    );
  });

  it("draws the list's icon in a tile", () => {
    render(<TaskListHeader name='House' icon='house' tasks={[]} />);

    const tile = screen.getByTestId('task-list-icon');
    expect(tile.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('draws no tile for a list without an icon', () => {
    render(<TaskListHeader name='House' icon={null} tasks={[]} />);

    expect(screen.queryByTestId('task-list-icon')).not.toBeInTheDocument();
  });
});
