/**
 * DashboardSectionPlaceholder — the two things a section can hold nothing for
 * that are not "nothing to hold".
 *
 * The three evidence cards each face the same three-way choice, and the
 * specification's *"sections render independently"* depends on keeping them
 * apart: **nothing scheduled / nothing due / nothing coming up** is a real
 * answer and gets the section's own **W29** line; a read still **in flight**
 * and a section that came back **unavailable** must not borrow it, because
 * "nothing due in the next seven days" would be a false claim about either.
 *
 * Phases 4, 7, 12 and 14 each shipped one muted line for both and recorded that
 * the real treatment was Phase 16's. This is it, and it is one component rather
 * than three near-identical per-card ones: the sentences differ per section and
 * come in as `copy`, but the *shape* of both states is a property of the page,
 * not of any one section. The wireframe depicts neither (gap 9) and directs
 * both to the idiom of **W9** and **W29**, which is what they follow — a
 * pulsing run of rows, and one centred icon over one muted line.
 *
 * The unavailable icon is shared across all three sections on purpose: it is
 * what makes *unavailable* one recognisable state rather than three, and the
 * sentence beside it already names which section is missing. There is no retry
 * control, per **W9** and per the page's rule that exactly two things here
 * write — recovery is the window-focus refetch and the anchor-day refresh.
 */

import { CloudOff } from 'lucide-react';
import { DashboardSectionSkeleton } from './DashboardSectionSkeleton';
import { WidgetEmptyState } from '@/components/journals/WidgetEmptyState';

/** The two sentences a section supplies; both are its own wording. */
export interface DashboardSectionPlaceholderCopy {
  readonly loading: string;
  readonly unavailable: string;
}

interface DashboardSectionPlaceholderProps {
  /** Whether the dashboard query is still in flight. */
  readonly pending: boolean;
  readonly copy: DashboardSectionPlaceholderCopy;
  /**
   * The section's id — `agenda`, `tasks`, `upcoming-dates`. The two states are
   * published as `${prefix}-loading` and `${prefix}-unavailable`, which are the
   * handles the cards' suites and the e2e already use: Phase 16 replaces the
   * rendering, not the way a test reaches it.
   */
  readonly testIdPrefix: string;
}

export function DashboardSectionPlaceholder({
  pending,
  copy,
  testIdPrefix,
}: DashboardSectionPlaceholderProps) {
  if (pending) {
    return (
      <DashboardSectionSkeleton
        label={copy.loading}
        testId={`${testIdPrefix}-loading`}
      />
    );
  }

  // Also the rendering for a dashboard request that failed outright, where
  // there is no envelope at all and so no section to have reported itself.
  return (
    <WidgetEmptyState
      icon={CloudOff}
      message={copy.unavailable}
      data-testid={`${testIdPrefix}-unavailable`}
    />
  );
}
