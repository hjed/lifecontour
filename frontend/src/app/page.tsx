/**
 * The home page: the user's daily briefing.
 *
 * It answers, in one screen, what is on today, what is coming that might be
 * forgotten, and what was promised — replacing the placeholder card grid
 * entirely (specification §*The Home Dashboard*).
 *
 * The frame is **W1**–**W4**: no new chrome (the root layout already supplies
 * the header, the sidebar and the page container, so this page deliberately
 * adds no container of its own), a page header anchored on the server's today,
 * and the three evidence sections in one independent-height row that stacks to
 * a single column below `lg` in the order Agenda → Tasks → Upcoming dates.
 *
 * The page reads `useHomeDashboard()` for the header's day alone — the header
 * takes it as a prop, which keeps it a pure function of the anchor and testable
 * without a query. **The summary, agenda and upcoming-dates cards call the same
 * hook themselves**, and the tasks card will as it is filled in.
 *
 * That is the arrangement rather than threading props down from here, and the
 * reason is per-section resilience: a card that owns its own read owns its own
 * loading and unavailable states, and its own error boundary. It costs nothing
 * because the hook has one query key, so every caller on the page dedupes into
 * a single fetch — asserted here, with the card mounted, and again in the
 * hook's own tests.
 *
 * The one thing the page owns rather than a card is **when the read expires**:
 * every window on it hangs off the single `meta.anchor` day, so the refresh at
 * that day's end is scheduled here, once, for all four of them.
 *
 * The summary card (**W5**–**W10**) sits above the grid.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { AgendaCard } from '@/components/dashboard/AgendaCard';
import { DashboardPageHeader } from '@/components/dashboard/DashboardPageHeader';
import { DashboardSection } from '@/components/dashboard/DashboardSection';
import { DashboardSummaryCard } from '@/components/dashboard/DashboardSummaryCard';
import { TasksCard } from '@/components/dashboard/TasksCard';
import { UpcomingDatesCard } from '@/components/dashboard/UpcomingDatesCard';
import {
  useAnchorDayRefresh,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';

function HomeDashboard() {
  const { data } = useHomeDashboard();

  // Once, here, rather than in each card: every card reads the same query key,
  // so four schedulers would be four timers invalidating one query. See
  // `useAnchorDayRefresh` for why the boundary is midnight in the anchor's own
  // zone and not a fixed interval.
  useAnchorDayRefresh(data?.meta.anchor);

  return (
    <div className='space-y-4' data-testid='home-dashboard-ready'>
      <DashboardPageHeader anchorDate={data?.meta.anchor.date} />

      {/* The headline, full width and directly above the evidence (W5). */}
      <DashboardSummaryCard />

      {/* `items-start` so a short Upcoming-dates card does not stretch to
          match a tall Agenda; below `lg` the three stack in this DOM order. */}
      <div
        className='grid grid-cols-1 items-start gap-4 lg:grid-cols-3'
        data-testid='dashboard-sections'
      >
        <DashboardSection id='agenda' title='Agenda'>
          <AgendaCard />
        </DashboardSection>

        <DashboardSection id='tasks' title='Tasks'>
          <TasksCard />
        </DashboardSection>

        <DashboardSection id='upcoming-dates' title='Upcoming dates'>
          <UpcomingDatesCard />
        </DashboardSection>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <AuthGuard>
      <HomeDashboard />
    </AuthGuard>
  );
}
