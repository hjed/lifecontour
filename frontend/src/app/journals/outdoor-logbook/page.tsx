/**
 * Outdoor Logbook overview page.
 *
 * The home for outdoor logbook review and reporting: a headline stat row over a
 * bento grid of the review and reporting widgets — incomplete activities,
 * recent activity totals, upcoming activities, checked-out gear, and the
 * abseil templates done.
 *
 * The grid is deliberately uncapped in width (the root layout's container is
 * the only bound) so the three columns have room; it collapses to a single
 * column below `lg`, where every explicit placement drops away.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { ActivityTotalsChart } from '@/components/journals/ActivityTotalsChart';
import { CheckedOutGearList } from '@/components/journals/CheckedOutGearList';
import { IncompleteOutdoorActivitiesList } from '@/components/journals/IncompleteOutdoorActivitiesList';
import { OutdoorLogbookStats } from '@/components/journals/OutdoorLogbookStats';
import { TemplatesDoneList } from '@/components/journals/TemplatesDoneList';
import { UpcomingActivitiesList } from '@/components/journals/UpcomingActivitiesList';

export default function OutdoorLogbookPage() {
  return (
    <AuthGuard>
      <div className='container mx-auto space-y-4 py-6'>
        <header className='space-y-1'>
          <h1 className='text-2xl font-bold tracking-tight'>Outdoor Logbook</h1>
          <p className='text-muted-foreground'>
            Review and reporting for your outdoor activities.
          </p>
        </header>

        <OutdoorLogbookStats />

        <div className='grid grid-cols-1 items-start gap-4 lg:grid-cols-3'>
          {/* Review and reporting take a column each; the two smaller
              read-only widgets stack inside the third. Stacking them in one
              grid cell (rather than giving each its own row) keeps them
              adjacent — separate rows would be stretched apart by the taller
              cards beside them. */}
          <section aria-labelledby='incomplete-activities-heading'>
            <h2 id='incomplete-activities-heading' className='sr-only'>
              Incomplete activities
            </h2>
            <IncompleteOutdoorActivitiesList />
          </section>

          <section aria-labelledby='activity-totals-heading'>
            <h2 id='activity-totals-heading' className='sr-only'>
              Recent activity totals
            </h2>
            <ActivityTotalsChart />
          </section>

          <div className='flex flex-col gap-4'>
            <section aria-labelledby='upcoming-activities-heading'>
              <h2 id='upcoming-activities-heading' className='sr-only'>
                Upcoming activities
              </h2>
              <UpcomingActivitiesList />
            </section>

            <section aria-labelledby='checked-out-gear-heading'>
              <h2 id='checked-out-gear-heading' className='sr-only'>
                Gear currently checked out
              </h2>
              <CheckedOutGearList />
            </section>
          </div>

          <section
            aria-labelledby='templates-done-heading'
            className='lg:col-span-3'
          >
            <h2 id='templates-done-heading' className='sr-only'>
              Abseil templates done
            </h2>
            <TemplatesDoneList />
          </section>
        </div>
      </div>
    </AuthGuard>
  );
}
