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
 * This page is the dashboard's only `useHomeDashboard()` caller today, because
 * it is the only part of it that needs data: the header takes its day as a
 * prop, which keeps it a pure function of the anchor and testable without a
 * query, and the three cards render nothing from the payload yet.
 *
 * The hook is nonetheless written to be called from anywhere — one query key,
 * so concurrent mounts dedupe into a single fetch (asserted in its own tests) —
 * because that is what lets Phases 4, 7, 12 and 14 read it from inside each
 * card. Reading it there rather than threading props down from here is what
 * makes a section's loading and unavailable states its own, which is the
 * per-section resilience the specification asks for and Phase 16 builds.
 *
 * The summary card (**W5**–**W10**) sits above the grid and lands in Phase 4;
 * the sections' own contents land in Phases 7, 12, 14 and 15.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { AgendaCard } from '@/components/dashboard/AgendaCard';
import { DashboardPageHeader } from '@/components/dashboard/DashboardPageHeader';
import { DashboardSection } from '@/components/dashboard/DashboardSection';
import { TasksCard } from '@/components/dashboard/TasksCard';
import { UpcomingDatesCard } from '@/components/dashboard/UpcomingDatesCard';
import { useHomeDashboard } from '@/lib/api/home-dashboard';

function HomeDashboard() {
  const { data } = useHomeDashboard();

  return (
    <div className='space-y-4' data-testid='home-dashboard-ready'>
      <DashboardPageHeader anchorDate={data?.meta.anchor.date} />

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
