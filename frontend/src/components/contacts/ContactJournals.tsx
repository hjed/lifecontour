/**
 * ContactJournals component displays all journals associated with a contact.
 *
 * Groups journals by relationship type (PARTICIPANT, INVITEE, ABOUT, MENTION)
 * with collapsible sections for each type.
 */

'use client';

import { useState } from 'react';
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

/**
 * Collapsible section for a specific relationship type
 */
function RelationshipSection({
  type,
  journals,
  defaultOpen = false,
}: {
  type: RelationshipType;
  journals: ReturnType<typeof useDisplayJournals>;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  if (journals.length === 0) return null;

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
            {journals.map(journal => (
              <JournalListItem key={journal.id} journal={journal} />
            ))}
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
  const { data, isLoading, isError, error } = useContactJournals(contactId);

  const journals = data?.data || [];

  // Convert to display journals (must be called unconditionally)
  const displayJournals = useDisplayJournals(journals);

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

  // Group journals by relationship type
  const journalsByType = displayJournals.reduce(
    (acc, journal) => {
      // Find the contact's relationship type in this journal
      const contactRelationship = journal.contacts.find(
        c => c.id === Number(contactId)
      );
      if (contactRelationship?.relationship_type) {
        const type = contactRelationship.relationship_type as RelationshipType;
        if (!acc[type]) acc[type] = [];
        acc[type].push(journal);
      }
      return acc;
    },
    {} as Record<RelationshipType, typeof displayJournals>
  );

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
      <div className='space-y-3'>
        {(Object.keys(RELATIONSHIP_LABELS) as RelationshipType[]).map(type => (
          <RelationshipSection
            key={type}
            type={type}
            journals={journalsByType[type] || []}
            defaultOpen={type === 'PARTICIPANT'}
          />
        ))}
      </div>
    </div>
  );
}
