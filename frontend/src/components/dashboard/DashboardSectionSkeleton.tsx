/**
 * DashboardSectionSkeleton — what a section draws while its read is in flight.
 *
 * The wireframe depicts no loading state for any of the three evidence sections
 * (gap 9), so this is built in **W9**'s quiet idiom: a run of rows in the same
 * bordered, accent-barred shape the sections really draw, pulsing. A skeleton is
 * a promise about what is arriving, which is why it follows the *row* idiom
 * rather than `ui/loading.tsx`'s `ListSkeleton` — that one is avatar-led, which
 * describes the upcoming-dates rows and mis-describes the other two.
 *
 * **It is deliberately not a live region.** Four of these mount at once on the
 * page every sign-in lands on, and `role="status"` would announce four loading
 * sentences to a screen-reader user who asked for none — the same noise Phase 4
 * refused `aria-live` on the summary body to avoid. Instead the container is
 * `aria-busy`, so the section reads as unfinished rather than as empty, and
 * carries the sentence the placeholder line used to show as visually hidden
 * text: there to be found, not read out. The bars themselves are decoration and
 * are hidden outright.
 */

import { Skeleton } from '@/components/ui/skeleton';

/** How many rows a section promises while it has none. */
const SKELETON_ROWS = 3;

interface DashboardSectionSkeletonProps {
  /**
   * What is loading, as a sentence. Required rather than optional: a skeleton
   * with no text is a section that says nothing at all to a reader who cannot
   * see it pulsing.
   */
  readonly label: string;
  /** The section's own loading id, so the card keeps the handle it published. */
  readonly testId: string;
  readonly rows?: number;
}

export function DashboardSectionSkeleton({
  label,
  testId,
  rows = SKELETON_ROWS,
}: DashboardSectionSkeletonProps) {
  return (
    <div aria-busy='true' className='space-y-3 pt-1' data-testid={testId}>
      <span className='sr-only'>{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={`dashboard-section-skeleton-${index}`}
          aria-hidden='true'
          data-testid='dashboard-section-skeleton-row'
          className='border-border relative overflow-hidden rounded-lg border py-3 pr-3 pl-4'
        >
          {/* The accent bar every row carries (W17, W22), muted: the colour is
              a property of the entry, and there is no entry yet. */}
          <span className='bg-muted absolute inset-y-0 left-0 w-1' />
          <div className='min-w-0 space-y-2'>
            <Skeleton className='h-4 w-3/5' />
            <Skeleton className='h-3 w-2/5' />
          </div>
        </div>
      ))}
    </div>
  );
}
