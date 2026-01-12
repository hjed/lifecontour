/**
 * JournalDetailView component for displaying full journal details.
 *
 * Main component that orchestrates all Phase 4 components to display
 * a complete journal view with breadcrumb, metadata, content, and children.
 */

'use client';

import { useState } from 'react';
import { Calendar, Edit, Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import type {
  Journal,
  JournalCalendar,
  JournalContactRelationship,
} from '@/types/journals';
import { JournalContactRelationshipType } from '@/types/journals';
import { JournalBreadcrumb } from './JournalBreadcrumb';
import { JournalTypeBadges } from './JournalTypeBadges';
import { JournalCalendarBadge } from './JournalCalendarBadge';
import { JournalContactBadge } from './JournalContactBadge';
import { JournalTagBadge } from './JournalTagBadge';
import { JournalChildrenList } from './JournalChildrenList';
import { JournalTypeDataDisplay } from './JournalTypeDataDisplay';
import {
  useUpdateJournal,
  useDeleteJournal,
  useAddContactRelationship,
  useRemoveContactRelationship,
  useAddJournalTag,
  useRemoveJournalTag,
  useJournalTags,
} from '@/lib/api/journals';
import { useContacts } from '@/lib/api/contacts';
import { useRouter } from 'next/navigation';

interface JournalDetailViewProps {
  readonly journal: Journal;
  readonly onEdit?: () => void;
  readonly className?: string;
}

/**
 * Full journal detail view component.
 * Displays all journal information with inline editing capabilities.
 */
export function JournalDetailView({
  journal,
  onEdit,
  className,
}: JournalDetailViewProps) {
  const router = useRouter();
  // Note: Calendar fetching will be implemented when calendar API is available
  const [availableCalendars] = useState<JournalCalendar[]>([]);

  // Mutations
  const updateJournal = useUpdateJournal();
  const deleteJournal = useDeleteJournal();
  const addContact = useAddContactRelationship();
  const removeContact = useRemoveContactRelationship();
  const addTag = useAddJournalTag();
  const removeTag = useRemoveJournalTag();

  // Data fetching
  const { data: tagsResponse } = useJournalTags();
  const { data: contactsResponse } = useContacts({}, { enabled: true });

  const availableTags = tagsResponse?.data || [];
  const availableContacts =
    contactsResponse?.data.map(c => ({
      id: Number.parseInt(c.id, 10),
      name: `${c.attributes.first_name} ${c.attributes.last_name || ''}`.trim(),
    })) || [];

  // Handlers
  const handleCalendarChange = async (calendarId: string) => {
    await updateJournal.mutateAsync({
      id: journal.id,
      data: {
        type_data: {
          ...journal.type_data,
          CALENDAR_INFO: {
            calendar_id: calendarId,
            is_all_day: false,
            sync_invitees: false,
          },
        },
      },
    });
  };

  const handleContactAdd = async (
    contactId: number,
    relationshipType: JournalContactRelationshipType
  ) => {
    await addContact.mutateAsync({
      journalId: journal.id,
      contactId: contactId.toString(),
      relationshipType,
    });
  };

  const handleContactRemove = async (contactId: number) => {
    const contact = journal.contacts.find(
      (c: JournalContactRelationship) => c.id === contactId
    );
    if (!contact) return;

    await removeContact.mutateAsync({
      journalId: journal.id,
      contactId: contactId.toString(),
      relationshipType: contact.relationship_type,
    });
  };

  const handleTagAdd = async (tagId: number) => {
    await addTag.mutateAsync({
      journalId: journal.id,
      tagId: tagId.toString(),
    });
  };

  const handleTagRemove = async (tagId: number) => {
    await removeTag.mutateAsync({
      journalId: journal.id,
      tagId: tagId.toString(),
    });
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this journal?')) return;

    await deleteJournal.mutateAsync(journal.id);
    router.push('/journals');
  };

  const formattedDate = journal.event_date_range?.start
    ? new Date(journal.event_date_range.start).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : null;

  return (
    <div
      className={cn('space-y-6', className)}
      data-testid='journal-detail-view'
    >
      {/* Breadcrumb Navigation */}
      <JournalBreadcrumb parent={journal.parent} currentTitle={journal.title} />

      {/* Main Content Card */}
      <Card>
        <CardHeader>
          <div className='flex items-start justify-between gap-4'>
            <div className='flex-1 space-y-2'>
              <CardTitle className='text-2xl'>{journal.title}</CardTitle>

              {/* Date */}
              {formattedDate && (
                <div className='text-muted-foreground flex items-center gap-2 text-sm'>
                  <Calendar className='h-4 w-4' />
                  {formattedDate}
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className='flex gap-2'>
              {onEdit && (
                <Button variant='outline' size='sm' onClick={onEdit}>
                  <Edit className='h-4 w-4' />
                </Button>
              )}
              <Button
                variant='outline'
                size='sm'
                onClick={handleDelete}
                disabled={deleteJournal.isPending}
              >
                <Trash2 className='h-4 w-4' />
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className='space-y-6'>
          {/* Type Badges */}
          <JournalTypeBadges types={journal.types} />

          {/* Metadata Section */}
          <div className='space-y-4'>
            {/* Calendar */}
            <div className='space-y-2'>
              <div className='text-sm font-medium'>Calendar</div>
              <JournalCalendarBadge
                calendar={journal.calendar}
                journalTypes={journal.types}
                onCalendarChange={handleCalendarChange}
                availableCalendars={availableCalendars}
              />
            </div>

            {/* Contacts */}
            <div className='space-y-2'>
              <div className='text-sm font-medium'>Contacts</div>
              <JournalContactBadge
                contacts={journal.contacts}
                onContactAdd={handleContactAdd}
                onContactRemove={handleContactRemove}
                availableContacts={availableContacts}
              />
            </div>

            {/* Tags */}
            <div className='space-y-2'>
              <div className='text-sm font-medium'>Tags</div>
              <JournalTagBadge
                tags={journal.tags}
                onTagAdd={handleTagAdd}
                onTagRemove={handleTagRemove}
                availableTags={availableTags}
              />
            </div>
          </div>

          <Separator />

          {/* Content */}
          <div className='prose prose-sm dark:prose-invert max-w-none'>
            <div className='whitespace-pre-wrap'>{journal.content}</div>
          </div>

          {/* Type-Specific Data */}
          <JournalTypeDataDisplay
            types={journal.types}
            typeData={journal.type_data}
          />
        </CardContent>
      </Card>

      {/* Children List */}
      {journal.children && journal.children.length > 0 && (
        <JournalChildrenList childJournals={journal.children} />
      )}
    </div>
  );
}
