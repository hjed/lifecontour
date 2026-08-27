/**
 * @jest-environment jsdom
 *
 * The three evidence cards as this phase ships them: their wireframe headers
 * (**W11**, **W21**, **W30**), the labelled list container each will fill in a
 * later phase (**W4**), and the single quiet line each shows while it holds
 * nothing (**W29** and the wireframe's gaps 1 and 2).
 */

import { render, screen } from '@testing-library/react';
import { AgendaCard } from '../AgendaCard';
import { TasksCard } from '../TasksCard';
import { UpcomingDatesCard } from '../UpcomingDatesCard';

describe.each([
  {
    name: 'AgendaCard',
    Card: AgendaCard,
    title: 'Agenda',
    description: "Today's schedule in time order, all-day items first.",
    listLabel: "Today's agenda",
    empty: 'Nothing scheduled today.',
  },
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
