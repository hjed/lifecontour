/**
 * Outdoor Logbook overview page.
 *
 * The home for outdoor logbook review and reporting: the incomplete outdoor
 * activities review and the dashboard widgets — upcoming activities and
 * recent activity totals now, with checked-out gear and templates done to
 * follow.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { ActivityTotalsTable } from '@/components/journals/ActivityTotalsTable';
import { IncompleteOutdoorActivitiesList } from '@/components/journals/IncompleteOutdoorActivitiesList';
import { UpcomingActivitiesList } from '@/components/journals/UpcomingActivitiesList';

export default function OutdoorLogbookPage() {
  return (
    <AuthGuard>
      <div className='container mx-auto max-w-4xl space-y-6 py-6'>
        <header className='space-y-1'>
          <h1 className='text-2xl font-bold tracking-tight'>Outdoor Logbook</h1>
          <p className='text-muted-foreground'>
            Review and reporting for your outdoor activities.
          </p>
        </header>

        <section aria-labelledby='incomplete-activities-heading'>
          <h2 id='incomplete-activities-heading' className='sr-only'>
            Incomplete activities
          </h2>
          <IncompleteOutdoorActivitiesList />
        </section>

        <section aria-labelledby='upcoming-activities-heading'>
          <h2 id='upcoming-activities-heading' className='sr-only'>
            Upcoming activities
          </h2>
          <UpcomingActivitiesList />
        </section>

        <section aria-labelledby='activity-totals-heading'>
          <h2 id='activity-totals-heading' className='sr-only'>
            Recent activity totals
          </h2>
          <ActivityTotalsTable />
        </section>
      </div>
    </AuthGuard>
  );
}
