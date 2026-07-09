/**
 * Outdoor Logbook overview page.
 *
 * The home for outdoor logbook review and reporting: currently the incomplete
 * outdoor activities review, with the dashboard widgets (upcoming activities,
 * checked-out gear, recent totals, templates done) to follow (ITER16-003).
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { IncompleteOutdoorActivitiesList } from '@/components/journals/IncompleteOutdoorActivitiesList';

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
      </div>
    </AuthGuard>
  );
}
