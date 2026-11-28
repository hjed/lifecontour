/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { TaskListBreadcrumb } from '../TaskListBreadcrumb';

function renderBreadcrumb(name = 'House') {
  render(<TaskListBreadcrumb name={name} />);
  return screen.getByRole('navigation', { name: 'Breadcrumb' });
}

describe('TaskListBreadcrumb', () => {
  it('lists Home, Tasks and the list in order', () => {
    const nav = renderBreadcrumb();

    const items = within(within(nav).getByRole('list')).getAllByRole(
      'listitem'
    );
    expect(items.map(item => item.textContent)).toEqual([
      'Home',
      'Tasks',
      'House',
    ]);
  });

  it('links Home to the home page', () => {
    const nav = renderBreadcrumb();

    expect(within(nav).getByRole('link', { name: 'Home' })).toHaveAttribute(
      'href',
      '/'
    );
  });

  it('does not link Tasks while there is no Tasks page to go to', () => {
    const nav = renderBreadcrumb();

    expect(within(nav).getAllByRole('link')).toHaveLength(1);
    expect(within(nav).getByText('Tasks')).not.toHaveAttribute('href');
  });

  it('marks the list as the current page', () => {
    const nav = renderBreadcrumb('Packing for Tasmania');

    expect(within(nav).getByText('Packing for Tasmania')).toHaveAttribute(
      'aria-current',
      'page'
    );
  });
});
