/**
 * @jest-environment <rootDir>/jest.timezone-environment.cjs
 * @jest-environment-options {"timezone": "America/New_York"}
 *
 * The task row **near midnight, in a zone that is not the server's**.
 *
 * Two of the chip's inputs were resolved by the server against the user's
 * configured timezone: `days_away` counts from the window's first day in it,
 * and `due_journal.date` is a calendar day in it. A row that worked either out
 * from the browser's clock would be right most of the time and wrong in the
 * hours that matter, so this pins both against a browser whose own answer
 * would differ.
 *
 * The setup is chosen so a browser-derived answer is *visibly* wrong rather
 * than merely unproven: it is 23:30 on 30 July in New York, and the user's
 * configured zone is Sydney, where it is already 31 July.
 *
 * - A task the server says is due **today** falls on 31 July. Browser
 *   arithmetic against New York's 30 July would call it *Tomorrow*.
 * - A task two days out falls on Sunday 2 August. Parsing that as an *instant*
 *   would render it in New York as Saturday 1 August.
 *
 * Both wrong answers are asserted against, and a third test confirms the
 * worker really is on the earlier local day — otherwise the other two could
 * pass vacuously in a UTC worker.
 */

import { render, screen } from '@testing-library/react';
import { DashboardTaskRow } from '../DashboardTaskRow';
import type { HomeDashboardTask } from '@/lib/api/home-dashboard';

/** 23:30 on 30 July in New York — half an hour before the local day turns. */
const NEW_YORK_NEAR_MIDNIGHT = new Date('2026-07-31T03:30:00Z');

/** As the server resolved them in Sydney, where it is already 31 July. */
const DUE_TODAY: HomeDashboardTask = {
  task_id: 1,
  text: 'Confirm the caterer',
  due_journal: { id: 44, title: 'Friday planning', date: '2026-07-31' },
  days_away: 0,
  contacts: [],
};

const DUE_IN_TWO_DAYS: HomeDashboardTask = {
  ...DUE_TODAY,
  task_id: 2,
  due_journal: { id: 45, title: 'Sunday', date: '2026-08-02' },
  days_away: 2,
};

beforeEach(() => {
  jest.useFakeTimers().setSystemTime(NEW_YORK_NEAR_MIDNIGHT);
});

afterEach(() => {
  jest.useRealTimers();
});

describe('DashboardTaskRow near midnight in a non-server timezone', () => {
  it('says Today because the server did, not because the browser agrees', () => {
    render(<DashboardTaskRow task={DUE_TODAY} />);

    const chip = screen.getByTestId('dashboard-task-chip');
    expect(chip).toHaveTextContent('Today');
    // What a browser subtracting 30 July from 31 July would have said.
    expect(chip).not.toHaveTextContent('Tomorrow');
  });

  it('names the day the server resolved, not that date read as an instant', () => {
    render(<DashboardTaskRow task={DUE_IN_TWO_DAYS} />);

    const chip = screen.getByTestId('dashboard-task-chip');
    expect(chip).toHaveTextContent('Sun 2 Aug');
    // What `new Date('2026-08-02')` formatted in New York would have said.
    expect(chip).not.toHaveTextContent('Sat 1 Aug');
  });

  /**
   * The control. Without it, a worker that had quietly run in UTC would make
   * both tests above pass while proving nothing: in UTC the browser's day and
   * the server's agree, and every wrong answer this file exists to catch
   * disappears.
   */
  it('really is running on the earlier local day', () => {
    expect(new Date().toLocaleDateString('en-CA')).toBe('2026-07-30');
  });
});
