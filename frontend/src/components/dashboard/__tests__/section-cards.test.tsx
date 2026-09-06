/**
 * @jest-environment jsdom
 *
 * The evidence card that is still a shell: its wireframe header (**W21**), the
 * labelled list container Phases 14 and 15 will fill (**W4**), and the single
 * quiet line it shows while it holds nothing (**W29**).
 *
 * Two cards have now left this table, each when it started reading the
 * dashboard query — the agenda in Phase 7, the upcoming dates in Phase 12 —
 * because a card with states of its own is tested beside them rather than
 * against a shared shell checklist. Their assertions live in `AgendaCard.
 * test.tsx` and `UpcomingDatesCard.test.tsx`, and this file goes with the tasks
 * card's own phase.
 */

import { render, screen } from '@testing-library/react';
import { TasksCard } from '../TasksCard';

const TITLE = 'Tasks';
const DESCRIPTION =
  'Due in the next seven days, soonest first. Tick them off here.';
const LIST_LABEL = 'Tasks due in the next seven days';
const EMPTY_LINE = 'Nothing due in the next seven days.';

describe('TasksCard', () => {
  it('carries its wireframe title and description', () => {
    render(<TasksCard />);

    expect(
      screen.getByRole('heading', { level: 3, name: TITLE })
    ).toBeInTheDocument();
    expect(screen.getByText(DESCRIPTION)).toBeInTheDocument();
  });

  it('renders the labelled list its entries will fill', () => {
    render(<TasksCard />);

    expect(screen.getByRole('list', { name: LIST_LABEL })).toBeInTheDocument();
  });

  it('says in one line that it holds nothing, reading as a good outcome', () => {
    render(<TasksCard />);

    expect(screen.getByText(EMPTY_LINE)).toBeInTheDocument();
    // No error styling, no retry: W29 is a quiet line, not a failure.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /try again|retry/i })
    ).not.toBeInTheDocument();
  });

  it('marks its decorative icons as hidden from assistive tech', () => {
    const { container } = render(<TasksCard />);

    const icons = container.querySelectorAll('svg');
    expect(icons.length).toBeGreaterThan(0);
    icons.forEach(icon => {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });
  });
});
