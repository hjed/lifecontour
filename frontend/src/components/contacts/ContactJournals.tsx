/**
 * ContactJournals component displays all journals associated with a contact.
 *
 * Groups journals by relationship type (PARTICIPANT, INVITEE, ABOUT, MENTION)
 * with collapsible sections for each type.
 */

'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { ChevronDown, ChevronRight, Plus } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useContactJournals } from '@/lib/api/journals';
import { JournalListItem } from '@/components/journals/JournalListItem';
import { useDisplayJournals } from '@/hooks/useDisplayJournals';

interface ContactJournalsProps {
  readonly contactId: string;
}

// Relationship type labels
const RELATIONSHIP_LABELS = {
  PARTICIPANT: 'Participant',
  INVITEE: 'Invitee',
  ABOUT: 'About',
  MENTION: 'Mention',
} as const;

type RelationshipType = keyof typeof RELATIONSHIP_LABELS;

interface RelationshipSectionProps {
  readonly type: RelationshipType;
  readonly journals: ReturnType<typeof useDisplayJournals>;
  readonly defaultOpen?: boolean;
}

function compareByEventDateMostRecentFirst(
  a: RelationshipSectionProps['journals'][number],
  b: RelationshipSectionProps['journals'][number]
): number {
  const dateA = new Date(a.event_date_range.start).getTime();
  const dateB = new Date(b.event_date_range.start).getTime();
  return dateB - dateA;
}

function compareChildJournals(
  a: RelationshipSectionProps['journals'][number],
  b: RelationshipSectionProps['journals'][number]
): number {
  const dateA = new Date(a.event_date_range.start).getTime();
  const dateB = new Date(b.event_date_range.start).getTime();

  // Children ordered by event_date_range.start, then order field (spec)
  if (dateA !== dateB) return dateA - dateB;

  const orderA = a.order ?? Number.POSITIVE_INFINITY;
  const orderB = b.order ?? Number.POSITIVE_INFINITY;
  if (orderA !== orderB) return orderA - orderB;

  // Stable fallback
  return String(a.id).localeCompare(String(b.id));
}

/**
 * Collapsible section for a specific relationship type
 */
function RelationshipSection({
  type,
  journals,
  defaultOpen = false,
}: RelationshipSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  // Per-parent expand/collapse state. Undefined => expanded by default.
  const [childrenExpandedById, setChildrenExpandedById] = useState<
    Record<string, boolean>
  >({});

  const { rootJournals, childrenByParentId } = useMemo(() => {
    const journalById = new Map(journals.map(j => [String(j.id), j]));

    const childrenMap = new Map<string, typeof journals>();
    const roots: typeof journals = [];

    for (const journal of journals) {
      const parentId = journal.parent_id;
      const parentKey =
        parentId !== null && parentId !== undefined ? String(parentId) : null;

      // Only nest if the parent is present in this relationship-type group
      if (parentKey && journalById.has(parentKey)) {
        const existing = childrenMap.get(parentKey) ?? [];
        existing.push(journal);
        childrenMap.set(parentKey, existing);
      } else {
        roots.push(journal);
      }
    }

    roots.sort(compareByEventDateMostRecentFirst);
    childrenMap.forEach(children => {
      children.sort(compareChildJournals);
    });

    return { rootJournals: roots, childrenByParentId: childrenMap };
  }, [journals]);

  if (journals.length === 0) return null;

  const toggleChildren = (journalId: string) => {
    setChildrenExpandedById(prev => {
      const current = prev[journalId] ?? true;
      return { ...prev, [journalId]: !current };
    });
  };

  const renderJournalNode = (journal: (typeof journals)[number]) => {
    const children = childrenByParentId.get(String(journal.id)) ?? [];
    const hasChildren = children.length > 0;
    const isExpanded = childrenExpandedById[String(journal.id)] ?? true;

    return (
      <div key={journal.id} className='space-y-3'>
        <div className='flex items-start gap-2'>
          {hasChildren ? (
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='h-8 w-8 shrink-0'
              aria-label={`${isExpanded ? 'Collapse' : 'Expand'} child journals`}
              aria-expanded={isExpanded}
              aria-controls={`journal-children-${journal.id}`}
              data-testid={`journalChildrenToggle-${journal.id}`}
              onClick={e => {
                e.preventDefault();
                e.stopPropagation();
                toggleChildren(String(journal.id));
              }}
            >
              {isExpanded ? (
                <ChevronDown className='h-4 w-4' aria-hidden='true' />
              ) : (
                <ChevronRight className='h-4 w-4' aria-hidden='true' />
              )}
            </Button>
          ) : (
            <div className='h-8 w-8 shrink-0' aria-hidden='true' />
          )}

          <div className='min-w-0 flex-1'>
            <JournalListItem journal={journal} className='w-full' />
          </div>
        </div>

        {hasChildren && isExpanded ? (
          <div
            id={`journal-children-${journal.id}`}
            data-testid={`journalChildrenContainer-${journal.id}`}
            className='ml-6 space-y-3 border-l pl-4'
          >
            {children.map(child => renderJournalNode(child))}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <Card className='overflow-hidden'>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CardHeader className='p-4'>
          <CollapsibleTrigger asChild>
            <Button
              variant='ghost'
              className='flex w-full items-center justify-between p-0 hover:bg-transparent'
              aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${RELATIONSHIP_LABELS[type]}`}
              data-testid={`relationship-section-trigger-${type}`}
            >
              <CardTitle className='text-base font-semibold'>
                {RELATIONSHIP_LABELS[type]} ({journals.length})
              </CardTitle>
              {isOpen ? (
                <ChevronDown className='h-4 w-4' aria-hidden='true' />
              ) : (
                <ChevronRight className='h-4 w-4' aria-hidden='true' />
              )}
            </Button>
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className='space-y-3 p-4 pt-0'>
            {rootJournals.map(journal => renderJournalNode(journal))}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

/**
 * ContactJournals component displays all journals for a contact grouped by relationship type
 */
export function ContactJournals({ contactId }: ContactJournalsProps) {
  // Fetch journals with maximum limit (100) to show as many as possible
  // Note: If a contact has >100 journals, we'd need to implement pagination UI
  const { data, isLoading, isError, error } = useContactJournals(contactId, {
    limit: 100,
  });

  const journals = data?.data || [];
  const meta = data?.meta;

  // Convert to display journals (must be called unconditionally)
  const displayJournals = useDisplayJournals(journals);

  // Must be called unconditionally (React hook ordering)
  const { journalsByType, directlyRelatedCount } = useMemo(() => {
    // Map for quick parent lookups (used to inherit relationship type for descendants)
    const journalById = new Map(displayJournals.map(j => [String(j.id), j]));

    const resolvedTypeById = new Map<string, RelationshipType | null>();

    const resolveRelationshipType = (
      journalId: string,
      visiting: Set<string>
    ): RelationshipType | null => {
      const cached = resolvedTypeById.get(journalId);
      if (cached !== undefined) return cached;

      if (visiting.has(journalId)) {
        // Defensive: break cycles (should not occur in valid hierarchy)
        resolvedTypeById.set(journalId, null);
        return null;
      }

      const journal = journalById.get(journalId);
      if (!journal) {
        resolvedTypeById.set(journalId, null);
        return null;
      }

      // Direct relationship takes precedence
      const direct = journal.contacts.find(c => c.id === contactId);
      if (direct?.relationship_type) {
        const type = direct.relationship_type as RelationshipType;
        resolvedTypeById.set(journalId, type);
        return type;
      }

      // Otherwise inherit from nearest ancestor that is directly related
      const parentId = journal.parent_id;
      if (parentId !== null && parentId !== undefined) {
        const parentKey = String(parentId);
        if (journalById.has(parentKey)) {
          visiting.add(journalId);
          const inherited = resolveRelationshipType(parentKey, visiting);
          visiting.delete(journalId);
          resolvedTypeById.set(journalId, inherited);
          return inherited;
        }
      }

      resolvedTypeById.set(journalId, null);
      return null;
    };

    const acc = {} as Record<RelationshipType, typeof displayJournals>;
    let directCount = 0;

    for (const journal of displayJournals) {
      const direct = journal.contacts.find(c => c.id === contactId);
      if (direct?.relationship_type) directCount += 1;

      const type = resolveRelationshipType(String(journal.id), new Set());
      if (!type) continue;
      if (!acc[type]) acc[type] = [];
      acc[type].push(journal);
    }

    // Sort journals within each type by event_date_range (most recent first)
    Object.keys(acc).forEach(type => {
      acc[type as RelationshipType].sort(compareByEventDateMostRecentFirst);
    });

    return { journalsByType: acc, directlyRelatedCount: directCount };
  }, [displayJournals, contactId]);

  // Loading state
  if (isLoading) {
    return (
      <div className='space-y-4'>
        <div className='flex items-center justify-between'>
          <h2 className='text-xl font-semibold'>Journals</h2>
        </div>
        <p className='text-muted-foreground'>Loading journals...</p>
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className='space-y-4'>
        <div className='flex items-center justify-between'>
          <h2 className='text-xl font-semibold'>Journals</h2>
        </div>
        <Alert variant='destructive'>
          <AlertDescription>
            Error loading journals: {error?.message || 'Unknown error'}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  // Empty state
  if (displayJournals.length === 0) {
    return (
      <div className='space-y-4'>
        <div className='flex items-center justify-between'>
          <h2 className='text-xl font-semibold'>Journals</h2>
          <Button size='sm' asChild>
            <Link href={`/journals/new?contact=${contactId}` as Route}>
              <Plus className='mr-2 h-4 w-4' />
              Add Journal
            </Link>
          </Button>
        </div>
        <p className='text-muted-foreground'>
          No journals found for this contact.
        </p>
      </div>
    );
  }

  // Check if there are more *directly-related* journals than displayed.
  // Backend pagination/meta is for directly-related journals, but the response
  // also includes their descendants.
  const totalRaw =
    (meta as Record<string, unknown> | undefined)?.total_count ??
    (meta as Record<string, unknown> | undefined)?.total;
  const totalJournals = typeof totalRaw === 'number' ? totalRaw : undefined;
  const hasMoreJournals =
    totalJournals !== undefined && totalJournals > directlyRelatedCount;

  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between'>
        <h2 className='text-xl font-semibold'>Journals</h2>
        <Button size='sm' asChild>
          <Link href={`/journals/new?contact=${contactId}` as Route}>
            <Plus className='mr-2 h-4 w-4' />
            Add Journal
          </Link>
        </Button>
      </div>

      {hasMoreJournals && (
        <Alert>
          <AlertDescription>
            Showing {directlyRelatedCount} of {totalJournals} related journals.
            Visit the{' '}
            <Link
              href='/journals'
              className='font-medium underline underline-offset-4'
            >
              Journals page
            </Link>{' '}
            to see all journals for this contact.
          </AlertDescription>
        </Alert>
      )}

      <div className='space-y-3'>
        {(Object.keys(RELATIONSHIP_LABELS) as RelationshipType[]).map(type => (
          <RelationshipSection
            key={type}
            type={type}
            journals={journalsByType[type] || []}
            defaultOpen={true}
          />
        ))}
      </div>
    </div>
  );
}
