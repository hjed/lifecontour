/**
 * JournalList component for displaying a grid of journal cards.
 *
 * Provides a responsive grid layout with empty state support.
 */

import { ReactNode } from 'react';
import { JournalListItem } from '@/components/journals/JournalListItem';
import { JournalResource } from '@/types/journals';

interface JournalListProps {
  readonly journals: JournalResource[];
  readonly emptyState?: ReactNode;
  readonly className?: string;
}

/**
 * Reusable journal list component
 * Displays journals in a responsive grid layout
 */
export function JournalList({
  journals,
  emptyState,
  className,
}: JournalListProps) {
  if (journals.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <div className={className || 'grid gap-4 md:grid-cols-2 lg:grid-cols-3'}>
      {journals.map(journal => (
        <JournalListItem key={journal.id} journal={journal} />
      ))}
    </div>
  );
}
