/**
 * Outdoor Logbook overview page.
 *
 * The home for outdoor logbook review and reporting: the incomplete outdoor
 * activities review and the four dashboard widgets — upcoming activities,
 * recent activity totals, checked-out gear, and the abseil templates done.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { ActivityTotalsTable } from '@/components/journals/ActivityTotalsTable';
import { CheckedOutGearList } from '@/components/journals/CheckedOutGearList';
import { IncompleteOutdoorActivitiesList } from '@/components/journals/IncompleteOutdoorActivitiesList';
import { TemplatesDoneList } from '@/components/journals/TemplatesDoneList';
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

        <section aria-labelledby='checked-out-gear-heading'>
          <h2 id='checked-out-gear-heading' className='sr-only'>
            Gear currently checked out
          </h2>
          <CheckedOutGearList />
        </section>

        <section aria-labelledby='templates-done-heading'>
          <h2 id='templates-done-heading' className='sr-only'>
            Abseil templates done
          </h2>
          <TemplatesDoneList />
        </section>
      </div>
    </AuthGuard>
  );
}
