/**
 * Contact ActivityFeed — thin wrapper over the shared, entity-agnostic
 * {@link SharedActivityFeed} that supplies the contact history hook.
 *
 * Kept at this path (and with the same props) so the contact detail page and
 * its tests are unaffected by the move to `components/history/`.
 */

'use client';

import { ActivityFeed as SharedActivityFeed } from '@/components/history/ActivityFeed';
import { useContactHistory } from '@/lib/api/contacts';

interface ActivityFeedProps {
  readonly contactId: string;
  readonly className?: string;
  /** Initial page size (default: 10) */
  readonly pageSize?: number;
}

export function ActivityFeed({
  contactId,
  className,
  pageSize,
}: ActivityFeedProps) {
  return (
    <SharedActivityFeed
      entity='contact'
      entityId={contactId}
      useHistory={useContactHistory}
      className={className}
      pageSize={pageSize}
    />
  );
}
