/**
 * JournalList component for displaying a hierarchical list of journal cards.
 *
 * Supports nested rendering when journals have parent/child relationships:
 * child journals are indented under their parents with expand/collapse controls.
 */

'use client';

import { ReactNode, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { JournalListItem } from '@/components/journals/JournalListItem';
import { DisplayJournal } from '@/hooks/useDisplayJournals';
import { useJournalTree, JournalTreeNode } from '@/hooks/useJournalTree';

interface JournalListProps {
  readonly journals: DisplayJournal[];
  readonly emptyState?: ReactNode;
  readonly className?: string;
}

/**
 * Reusable journal list component with hierarchical nesting.
 *
 * Journals with parent/child relationships are rendered as a tree:
 * - Parents show expand/collapse toggles
 * - Children are indented with a left border
 * - Orphans (parent not in list) appear at root level
 */
export function JournalList({
  journals,
  emptyState,
  className,
}: JournalListProps) {
  const tree = useJournalTree(journals);
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

  if (journals.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  const toggleExpanded = (journalId: string) => {
    setExpandedIds((prev: Record<string, boolean>) => {
      const current = prev[journalId] ?? true; // default expanded
      return { ...prev, [journalId]: !current };
    });
  };

  const renderNode = (node: JournalTreeNode) => {
    const hasInlineChildren = node.children.length > 0;
    const isExpanded = expandedIds[String(node.journal.id)] ?? true;

    return (
      <div key={node.journal.id} className='space-y-3'>
        <div className='flex items-start gap-2'>
          {hasInlineChildren && (
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='h-8 w-8 shrink-0'
              aria-label={`${isExpanded ? 'Collapse' : 'Expand'} child journals`}
              aria-expanded={isExpanded}
              aria-controls={`journal-children-${node.journal.id}`}
              data-testid={`journalChildrenToggle-${node.journal.id}`}
              onClick={(e: React.MouseEvent) => {
                e.preventDefault();
                e.stopPropagation();
                toggleExpanded(String(node.journal.id));
              }}
            >
              {isExpanded ? (
                <ChevronDown className='h-4 w-4' aria-hidden='true' />
              ) : (
                <ChevronRight className='h-4 w-4' aria-hidden='true' />
              )}
            </Button>
          )}
          {!hasInlineChildren && node.hasChildren && (
            /* Parent has DB children but they're not in this page */
            <div className='flex h-8 w-8 shrink-0 items-center justify-center'>
              <ChevronRight
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
            </div>
          )}
          {!hasInlineChildren && !node.hasChildren && (
            <div className='h-8 w-8 shrink-0' aria-hidden='true' />
          )}

          <div className='min-w-0 flex-1'>
            <JournalListItem journal={node.journal} className='w-full' />
          </div>
        </div>

        {hasInlineChildren && isExpanded ? (
          <div
            id={`journal-children-${node.journal.id}`}
            data-testid={`journalChildrenContainer-${node.journal.id}`}
            className='ml-6 space-y-3 border-l pl-4'
          >
            {node.children.map(child => renderNode(child))}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div className={className || 'space-y-3'}>
      {tree.map(rootNode => renderNode(rootNode))}
    </div>
  );
}
