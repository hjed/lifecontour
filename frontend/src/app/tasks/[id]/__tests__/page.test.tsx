/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import TaskListRoute, { metadata } from '../page';

jest.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => (
    <div data-testid='auth-guard'>{children}</div>
  ),
}));

jest.mock('@/components/tasks/TaskListPage', () => ({
  TaskListPage: ({ rawId }: { rawId: string }) => (
    <p data-testid='task-list-page'>{rawId}</p>
  ),
}));

describe('/tasks/[id]', () => {
  it('hands the route segment, unchecked, to the guarded list page', async () => {
    render(await TaskListRoute({ params: Promise.resolve({ id: 'abc' }) }));

    expect(screen.getByTestId('auth-guard')).toContainElement(
      screen.getByTestId('task-list-page')
    );
    expect(screen.getByTestId('task-list-page')).toHaveTextContent('abc');
  });

  it('titles the page', () => {
    expect(metadata.title).toBe('Task list');
  });
});
