/**
 * Task ActivityFeed — thin wrapper over the shared, entity-agnostic
 * {@link SharedActivityFeed} that supplies the task history hook.
 *
 * Mirrors `components/contacts/ActivityFeed.tsx` and
 * `components/journals/ActivityFeed.tsx` so all three surfaces share one feed
 * component, layout, provenance icons and pagination behaviour — which is what
 * the activity-history specification asks for, and the reason this is a
 * wrapper rather than a list of its own.
 *
 * There is no `enabled` prop, deliberately. A task has no route, so this feed
 * lives inside a journal's task row and a journal can hold many tasks; what
 * keeps those off the network is that the row **does not mount this component**
 * until its disclosure is opened. A flag would leave a hidden feed's card and
 * empty state in the DOM on every row to achieve less.
 */

'use client';

import { ActivityFeed as SharedActivityFeed } from '@/components/history/ActivityFeed';
import { useTaskHistory } from '@/lib/api/tasks';

interface TaskActivityFeedProps {
  readonly taskId: string;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
  /** The card heading, or `null` for none. See the shared feed's prop. */
  readonly title?: string | null;
}

export function TaskActivityFeed({
  taskId,
  className,
  pageSize,
  title,
}: TaskActivityFeedProps) {
  return (
    <SharedActivityFeed
      entity='task'
      entityId={taskId}
      useHistory={useTaskHistory}
      className={className}
      pageSize={pageSize}
      title={title}
    />
  );
}
