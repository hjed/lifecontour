/**
 * JournalDetailView component for displaying full journal details.
 *
 * Main component that orchestrates all Phase 4 components to display
 * a complete journal view with breadcrumb, metadata, content, and children.
 * Includes inline editing for title and content.
 */

'use client';

import { useCallback } from 'react';
import { Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import type {
  Journal,
  JournalCalendar,
  JournalContactRelationship,
  EventDateRange,
  AbseilingData,
  CalendarInfoData,
  CanyoningData,
  ClimbingData,
  CrossCountrySkiingData,
  KayakingData,
  MoodData,
  PhotoAlbumData,
  PlanData,
  TravelData,
  FitnessData,
  OutdoorActivityData,
  BushwalkingData,
  JoggingData,
  JournalTypeData,
} from '@/types/journals';
import { JournalContactRelationshipType, JournalType } from '@/types/journals';
import { JournalBreadcrumb } from './JournalBreadcrumb';
import { JournalCalendarBadge } from './JournalCalendarBadge';
import { JournalContactBadge } from './JournalContactBadge';
import { JournalTagBadge } from './JournalTagBadge';
import { JournalChildrenList } from './JournalChildrenList';
import { JournalTypeSection } from './JournalTypeSection';
import { JournalTypeManager } from './JournalTypeManager';
import { InlineEditHeading } from './InlineEditHeading';
import { JournalContentInline } from './JournalContentInline';
import { InlineEditDateRange } from './InlineEditDateRange';
import { validateRequired } from '@/lib/validation';
import {
  useUpdateJournal,
  useDeleteJournal,
  useAddContactRelationship,
  useRemoveContactRelationship,
  useAddJournalTag,
  useRemoveJournalTag,
  useJournalTags,
  useCalendars,
  useUpdateTypeData,
  useAddJournalType,
  useRemoveJournalType,
} from '@/lib/api/journals';
import { useContacts } from '@/lib/api/contacts';
import { useRouter } from 'next/navigation';

interface JournalDetailViewProps {
  readonly journal: Journal;
  readonly className?: string;
}

/**
 * Full journal detail view component.
 * Displays all journal information with inline editing capabilities.
 */
export function JournalDetailView({
  journal,
  className,
}: JournalDetailViewProps) {
  const router = useRouter();

  // Mutations
  const updateJournal = useUpdateJournal();
  const updateTypeData = useUpdateTypeData();
  const deleteJournal = useDeleteJournal();
  const addContact = useAddContactRelationship();
  const removeContact = useRemoveContactRelationship();
  const addTag = useAddJournalTag();
  const removeTag = useRemoveJournalTag();
  const addType = useAddJournalType();
  const removeType = useRemoveJournalType();

  // Data fetching
  const { data: tagsResponse } = useJournalTags();
  const { data: contactsResponse } = useContacts({}, { enabled: true });
  const { data: calendarsData } = useCalendars();

  const availableTags = tagsResponse?.data || [];
  const availableCalendars: JournalCalendar[] =
    calendarsData?.data.map(c => ({
      id: c.id,
      name: c.attributes.name,
      color: c.attributes.color,
    })) || [];
  const availableContacts =
    contactsResponse?.data.map(c => ({
      id: Number.parseInt(c.id, 10),
      name: `${c.attributes.first_name} ${c.attributes.last_name || ''}`.trim(),
    })) || [];

  // Handlers
  const handleCalendarChange = async (calendarId: string) => {
    await updateTypeData.mutateAsync({
      journalId: journal.id,
      journalType: JournalType.EVENT,
      typeData: {
        calendar_id: calendarId,
        is_all_day: false,
        sync_invitees: false,
      },
    });
  };

  const handleContactAdd = async (
    contactId: string,
    relationshipType: JournalContactRelationshipType
  ) => {
    await addContact.mutateAsync({
      journalId: journal.id,
      contactId: contactId,
      relationshipType,
    });
  };

  const handleContactRemove = async (contactId: string) => {
    const contact = journal.contacts.find(
      (c: JournalContactRelationship) => c.id === contactId
    );
    if (!contact) return;

    await removeContact.mutateAsync({
      journalId: journal.id,
      contactId: contactId,
      relationshipType: contact.relationship_type,
    });
  };

  const handleTagAdd = async (tagId: string) => {
    await addTag.mutateAsync({
      journalId: journal.id,
      tagId: tagId,
    });
  };

  const handleTagRemove = async (tagId: string) => {
    await removeTag.mutateAsync({
      journalId: journal.id,
      tagId: tagId,
    });
  };

  const handleDelete = async () => {
    if (!confirm('Are you sure you want to delete this journal?')) return;

    await deleteJournal.mutateAsync(journal.id);
    router.push('/journals');
  };

  const handleTypeAdd = async (type: JournalType) => {
    await addType.mutateAsync({
      journalId: journal.id,
      journalType: type,
    });
  };

  const handleTypeRemove = async (type: JournalType) => {
    await removeType.mutateAsync({
      journalId: journal.id,
      journalType: type,
    });
  };

  // Handle type-specific data update
  const handleTypeDataSave = useCallback(
    async (
      type: JournalType,
      data:
        | CalendarInfoData
        | MoodData
        | PhotoAlbumData
        | PlanData
        | TravelData
        | AbseilingData
        | CanyoningData
        | ClimbingData
        | KayakingData
        | CrossCountrySkiingData
        | FitnessData
        | OutdoorActivityData
        | BushwalkingData
        | JoggingData
    ) => {
      await updateTypeData.mutateAsync({
        journalId: journal.id,
        journalType: type,
        typeData: data as Record<string, unknown>,
      });
    },
    [journal.id, updateTypeData]
  );

  // Handle title update
  const handleTitleSave = useCallback(
    async (value: string) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          title: value,
        },
      });
    },
    [journal.id, updateJournal]
  );

  // Handle content update
  const handleContentSave = useCallback(
    async (value: string) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          content: value,
        },
      });
    },
    [journal.id, updateJournal]
  );

  // Handle date range update
  const handleDateRangeSave = useCallback(
    async (value: EventDateRange) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          event_date_range: value,
        },
      });
    },
    [journal.id, updateJournal]
  );

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
            <div className='flex-1 space-y-3'>
              {/* Title - Inline Editable */}
              <InlineEditHeading
                value={journal.title}
                onSave={handleTitleSave}
                level={2}
                validation={validateRequired}
                placeholder='Journal title'
                className='text-2xl font-bold tracking-tight'
                data-testid='journal-title-field'
              />

              {/* Date Range - Inline Editable */}
              {journal.event_date_range &&
                (journal.event_date_range.start ||
                  journal.event_date_range.end) && (
                  <InlineEditDateRange
                    value={journal.event_date_range}
                    onSave={handleDateRangeSave}
                    aria-label='Event date range'
                    data-testid='journal-date-range-field'
                  />
                )}
            </div>

            {/* Action Buttons */}
            <div className='flex gap-2'>
              <Button
                variant='outline'
                size='sm'
                onClick={handleDelete}
                disabled={deleteJournal.isPending}
                aria-label='Delete journal'
              >
                <Trash2 className='h-4 w-4' />
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className='space-y-6'>
          {/* Metadata Section */}
          <div className='space-y-4'>
            {/* Types */}
            <div className='space-y-2'>
              <div className='text-sm font-medium'>Types</div>
              <JournalTypeManager
                currentTypes={journal.types || []}
                onTypeAdd={handleTypeAdd}
                onTypeRemove={handleTypeRemove}
              />
            </div>

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

          {/* Content - Inline Editable */}
          <div>
            <h3 className='mb-2 text-sm font-medium'>Content</h3>
            <JournalContentInline
              value={journal.content}
              onSave={handleContentSave}
              placeholder='Add journal content...'
              data-testid='journal-content'
            />
          </div>

          {/* Type-Specific Data Sections */}
          {journal.types && journal.types.length > 0 && (
            <div className='space-y-4'>
              {journal.types.map(type => (
                <JournalTypeSection
                  key={type}
                  journalId={journal.id}
                  type={type}
                  typeData={journal.type_data?.[type] as JournalTypeData}
                  onSave={handleTypeDataSave}
                  defaultOpen={false}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Children List */}
      {journal.children && journal.children.length > 0 && (
        <JournalChildrenList childJournals={journal.children} />
      )}
    </div>
  );
}
