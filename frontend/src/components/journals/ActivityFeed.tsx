/**
 * Journal ActivityFeed — thin wrapper over the shared, entity-agnostic
 * {@link SharedActivityFeed} that supplies the journal history hook.
 *
 * Mirrors `components/contacts/ActivityFeed.tsx` so journals and contacts share
 * one feed component, layout, provenance icons, and pagination behaviour. The
 * `entity="journal"` prop drives the journal-specific empty-state copy.
 */

'use client';

import { ActivityFeed as SharedActivityFeed } from '@/components/history/ActivityFeed';
import { useJournalHistory } from '@/lib/api/journals';

interface ActivityFeedProps {
  readonly journalId: string;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
}

export function ActivityFeed({
  journalId,
  className,
  pageSize,
}: ActivityFeedProps) {
  return (
    <SharedActivityFeed
      entity='journal'
      entityId={journalId}
      useHistory={useJournalHistory}
      className={className}
      pageSize={pageSize}
    />
  );
}
