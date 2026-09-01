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
 * without a query. **The summary card calls the same hook itself**, and the
 * three section cards will as they are filled in.
 *
 * That is the arrangement rather than threading props down from here, and the
 * reason is per-section resilience: a card that owns its own read owns its own
 * loading and unavailable states, which is what the specification asks for and
 * Phase 16 builds. It costs nothing because the hook has one query key, so
 * every caller on the page dedupes into a single fetch — asserted here, with
 * the card mounted, and again in the hook's own tests.
 *
 * The summary card (**W5**–**W10**) sits above the grid; the sections' own
 * contents land in Phases 7, 12, 14 and 15.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { AgendaCard } from '@/components/dashboard/AgendaCard';
import { DashboardPageHeader } from '@/components/dashboard/DashboardPageHeader';
import { DashboardSection } from '@/components/dashboard/DashboardSection';
import { DashboardSummaryCard } from '@/components/dashboard/DashboardSummaryCard';
import { TasksCard } from '@/components/dashboard/TasksCard';
import { UpcomingDatesCard } from '@/components/dashboard/UpcomingDatesCard';
import { useHomeDashboard } from '@/lib/api/home-dashboard';

function HomeDashboard() {
  const { data } = useHomeDashboard();

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
