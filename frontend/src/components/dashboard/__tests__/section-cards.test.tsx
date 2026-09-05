/**
 * @jest-environment jsdom
 *
 * The evidence cards that are still shells: their wireframe headers (**W21**,
 * **W30**), the labelled list container each will fill in a later phase
 * (**W4**), and the single quiet line each shows while it holds nothing
 * (**W29** and the wireframe's gap 2).
 *
 * The agenda card left this table when it started reading the dashboard query;
 * its shell assertions live in `AgendaCard.test.tsx` beside its states.
 */

import { render, screen } from '@testing-library/react';
import { TasksCard } from '../TasksCard';
import { UpcomingDatesCard } from '../UpcomingDatesCard';

describe.each([
  {
    name: 'TasksCard',
    Card: TasksCard,
    title: 'Tasks',
    description:
      'Due in the next seven days, soonest first. Tick them off here.',
    listLabel: 'Tasks due in the next seven days',
    empty: 'Nothing due in the next seven days.',
  },
  {
    name: 'UpcomingDatesCard',
    Card: UpcomingDatesCard,
    title: 'Upcoming dates',
    description: 'Important dates for your contacts over the next seven days.',
    listLabel: 'Upcoming contact dates',
    empty: 'No important dates in the next seven days.',
  },
])('$name', ({ Card, title, description, listLabel, empty }) => {
  it('carries its wireframe title and description', () => {
    render(<Card />);

    expect(
      screen.getByRole('heading', { level: 3, name: title })
    ).toBeInTheDocument();
    expect(screen.getByText(description)).toBeInTheDocument();
  });

  it('renders the labelled list its entries will fill', () => {
    render(<Card />);

    expect(screen.getByRole('list', { name: listLabel })).toBeInTheDocument();
  });

  it('says in one line that it holds nothing, reading as a good outcome', () => {
    render(<Card />);

    expect(screen.getByText(empty)).toBeInTheDocument();
    // No error styling, no retry: W29 is a quiet line, not a failure.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /try again|retry/i })
    ).not.toBeInTheDocument();
  });

  it('marks its decorative icons as hidden from assistive tech', () => {
    const { container } = render(<Card />);

    const icons = container.querySelectorAll('svg');
    expect(icons.length).toBeGreaterThan(0);
    icons.forEach(icon => {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });
  });
});
