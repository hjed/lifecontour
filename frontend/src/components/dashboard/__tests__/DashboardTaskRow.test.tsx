/**
 * @jest-environment jsdom
 *
 * One task as the dashboard draws it (**W22**–**W27**).
 *
 * A pure function of a payload row — no query, no clock, and the action it
 * carries arrives as a slot — so these render it directly and assert its
 * *content*: the commitment, the chip, where the journal link points, who is
 * named on it, and the several things that must **not** appear.
 *
 * The near-midnight non-UTC case the phase asks for lives in
 * `DashboardTaskRow.timezone.test.tsx`, which needs a pinned process zone.
 */

import { render, screen, within } from '@testing-library/react';
import { DashboardTaskRow } from '../DashboardTaskRow';
import type { HomeDashboardTask } from '@/lib/api/home-dashboard';
import { expectWrapsLongWords } from '@/test-utils/home-dashboard';
import {
  dueAccentClassName,
  dueChipClassName,
  taskTextId,
} from '@/lib/dashboard-tasks-display';

function dashboardTask(
  overrides: Partial<HomeDashboardTask> = {}
): HomeDashboardTask {
  return {
    task_id: 12,
    text: 'Send Priya the deposit receipt',
    due_journal: { id: 44, title: 'Friday planning', date: '2026-08-01' },
    days_away: 2,
    contacts: [],
    ...overrides,
  };
}

describe('DashboardTaskRow', () => {
  it('draws the commitment as a prominent line that is not a link (W23)', () => {
    render(<DashboardTaskRow task={dashboardTask()} />);

    const text = screen.getByText('Send Priya the deposit receipt');
    expect(text).toBeInTheDocument();
    expect(text).toHaveClass('font-medium');
    // W23 says so in terms: "The task text as a prominent non-link line. The
    // task itself has no detail route."
    expect(text.closest('a')).toBeNull();
  });

  it('gives the text the id the row’s actions are described by', () => {
    render(<DashboardTaskRow task={dashboardTask({ task_id: 12 })} />);

    expect(screen.getByText('Send Priya the deposit receipt')).toHaveAttribute(
      'id',
      taskTextId(12)
    );
  });

  it.each([
    [0, '2026-07-29', 'Today'],
    [1, '2026-07-30', 'Tomorrow'],
    [2, '2026-08-01', 'Sat 1 Aug'],
    [7, '2026-08-05', 'Wed 5 Aug'],
  ])(
    'writes the due chip relatively first at %i days away (W25)',
    (days_away, date, expected) => {
      render(
        <DashboardTaskRow
          task={dashboardTask({
            days_away,
            due_journal: { id: 44, title: 'Friday planning', date },
          })}
        />
      );

      expect(screen.getByTestId('dashboard-task-chip')).toHaveTextContent(
        expected
      );
    }
  );

  /**
   * **W25**'s one explicit prohibition: the chip's colour follows the *due
   * journal*, not how soon the task falls due. Two tasks a week apart in the
   * same journal therefore match, and two due today in different journals do
   * not — which is the pair of assertions a proximity scale would fail.
   */
  it('colours the chip by the due journal, not by proximity (W25)', () => {
    const { rerender } = render(
      <DashboardTaskRow task={dashboardTask({ days_away: 0 })} />
    );
    const near = screen.getByTestId('dashboard-task-chip').className;

    rerender(<DashboardTaskRow task={dashboardTask({ days_away: 7 })} />);
    expect(screen.getByTestId('dashboard-task-chip').className).toBe(near);

    rerender(
      <DashboardTaskRow
        task={dashboardTask({
          days_away: 0,
          due_journal: { id: 45, title: 'Saturday', date: '2026-08-02' },
        })}
      />
    );
    expect(screen.getByTestId('dashboard-task-chip').className).not.toBe(near);
  });

  it('keys the accent bar to the same journal as the chip (W22)', () => {
    const { container } = render(
      <DashboardTaskRow
        task={dashboardTask({
          due_journal: { id: 44, title: 'Friday planning', date: '2026-08-01' },
        })}
      />
    );

    const accent = container.querySelector(
      '[data-testid="dashboard-task-accent"]'
    );
    expect(accent).toHaveClass(dueAccentClassName(44));
    expect(screen.getByTestId('dashboard-task-chip')).toHaveClass(
      ...dueChipClassName(44).split(' ')
    );
  });

  /**
   * The specification asks a row to show *"the due journal's title and date"*,
   * and **W25** makes the visible label relative for the first two days. Both
   * are satisfied: the words follow the wireframe and the date is carried in
   * the markup, so a row reading `Today` still says which day it means.
   */
  it('carries the due date in the markup even when the words are relative', () => {
    render(
      <DashboardTaskRow
        task={dashboardTask({
          days_away: 0,
          due_journal: { id: 44, title: 'Friday planning', date: '2026-07-29' },
        })}
      />
    );

    const chip = screen.getByTestId('dashboard-task-chip');
    expect(chip).toHaveTextContent('Today');
    expect(chip.tagName).toBe('TIME');
    expect(chip).toHaveAttribute('datetime', '2026-07-29');
  });

  it('links to the due journal under muted "Due in" text (W26)', () => {
    render(<DashboardTaskRow task={dashboardTask()} />);

    const link = screen.getByRole('link', { name: 'Friday planning' });
    expect(link).toHaveAttribute('href', '/journals/44');
    expect(screen.getByTestId('dashboard-task-due')).toHaveTextContent(
      'Due in Friday planning'
    );
  });

  it('names each linked contact beside an avatar (W27)', () => {
    render(
      <DashboardTaskRow
        task={dashboardTask({
          contacts: [
            { contact_id: 3, name: 'Priya Raman', photo_url: null },
            { contact_id: 9, name: 'Tom Ellis', photo_url: null },
          ],
        })}
      />
    );

    const contacts = screen.getByTestId('dashboard-task-contacts');
    expect(within(contacts).getByText('Priya Raman')).toBeInTheDocument();
    expect(within(contacts).getByText('Tom Ellis')).toBeInTheDocument();
    expect(within(contacts).getAllByRole('listitem')).toHaveLength(2);
  });

  /**
   * `ContactAvatar` carries `role="img"` with the contact's name as its
   * accessible name, and **W27** puts that same name in text right beside it —
   * so without this a screen reader reads every contact twice ("Priya Raman,
   * image, Priya Raman"). The avatar is the decorative half of the pair here,
   * because the text is the thing the sighted reader is reading too.
   *
   * Found by the PR review. Two more instances of the same pairing exist on
   * other phases' surfaces and are recorded as a follow-up rather than swept
   * up here.
   */
  it('announces each contact once, not once per avatar (W27)', () => {
    render(
      <DashboardTaskRow
        task={dashboardTask({
          contacts: [{ contact_id: 3, name: 'Priya Raman', photo_url: null }],
        })}
      />
    );

    expect(screen.getAllByText('Priya Raman')).toHaveLength(1);
    expect(
      screen.queryByRole('img', { name: 'Priya Raman' })
    ).not.toBeInTheDocument();
    // The avatar is still drawn — hidden from assistive tech, not removed.
    expect(screen.getByTestId('avatar-contact')).toBeInTheDocument();
  });

  it('renders nothing at all where a task names nobody (W27)', () => {
    render(<DashboardTaskRow task={dashboardTask({ contacts: [] })} />);

    expect(
      screen.queryByTestId('dashboard-task-contacts')
    ).not.toBeInTheDocument();
  });

  it('mounts the action it is handed, top-right of the text row (W24)', () => {
    render(
      <DashboardTaskRow
        task={dashboardTask()}
        actions={<button type='button'>Done</button>}
      />
    );

    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
  });

  /**
   * **AC5**: no overdue section, counter or badge appears anywhere on the
   * page, and a lapsed task never renders here.
   *
   * The row *cannot* draw either — the payload carries no `status`, no
   * `lapsed` and no `lapse_reason`, which is Phase 13's deliberate choice —
   * and these assertions are what keeps a later phase from reintroducing one
   * by copying the journal row, which draws all three.
   */
  it('carries no status badge, no lapsed marker and no overdue language (AC5)', () => {
    render(<DashboardTaskRow task={dashboardTask({ days_away: 0 })} />);

    expect(screen.queryByText(/overdue/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/lapsed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not done/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('journal-task-lapsed')).not.toBeInTheDocument();
  });

  it('marks its decorative icons as hidden from assistive tech', () => {
    const { container } = render(<DashboardTaskRow task={dashboardTask()} />);

    const icons = container.querySelectorAll('svg');
    expect(icons.length).toBeGreaterThan(0);
    icons.forEach(icon => {
      expect(icon).toHaveAttribute('aria-hidden', 'true');
    });
  });

  it('is a list item, so the card’s labelled list holds real entries (W4)', () => {
    render(
      <ul>
        <DashboardTaskRow task={dashboardTask()} />
      </ul>
    );

    expect(screen.getAllByRole('listitem')[0]).toHaveAttribute(
      'data-testid',
      'dashboard-task-12'
    );
  });

  /** See `expectWrapsLongWords`; the real measurement is in the e2e (W3). */
  describe('long unbroken content (W3)', () => {
    const UNBROKEN = 'Supercalifragilistic' + 'x'.repeat(120);

    it('lets a long commitment break rather than widen the column', () => {
      render(<DashboardTaskRow task={dashboardTask({ text: UNBROKEN })} />);

      expectWrapsLongWords(screen.getByText(UNBROKEN));
    });

    it('lets a long due-journal title break', () => {
      render(
        <DashboardTaskRow
          task={dashboardTask({
            due_journal: { id: 44, title: UNBROKEN, date: '2026-08-01' },
          })}
        />
      );

      expectWrapsLongWords(screen.getByTestId('dashboard-task-due'));
    });

    it('lets a long contact name break', () => {
      render(
        <DashboardTaskRow
          task={dashboardTask({
            contacts: [{ contact_id: 7, name: UNBROKEN, photo_url: null }],
          })}
        />
      );

      expectWrapsLongWords(screen.getByText(UNBROKEN));
    });
  });
});
