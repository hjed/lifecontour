/**
 * JournalDetailView component for displaying full journal details.
 *
 * Main component that orchestrates all Phase 4 components to display
 * a complete journal view with breadcrumb, metadata, content, and children.
 * Includes inline editing for title and content.
 */

'use client';

import { useCallback, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { isPast, parseISO } from 'date-fns';
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
  OutdoorPlanningData,
  OutdoorTrainingData,
  GearMaintenanceData,
  GearUsageData,
  JournalTypeData,
  ActivityTemplateResource,
} from '@/types/journals';
import {
  JournalContactRelationshipType,
  JournalType,
  AttendeeStatus,
  ContactEventRole,
} from '@/types/journals';
import { toast } from 'sonner';
import { JournalBreadcrumb } from './JournalBreadcrumb';
import { JournalCalendarBadge } from './JournalCalendarBadge';
import { JournalContactBadge } from './JournalContactBadge';
import { JournalTagBadge } from './JournalTagBadge';
import { JournalChildrenList } from './JournalChildrenList';
import { JournalParentSelector } from './JournalParentSelector';
import { JournalTypeSection } from './JournalTypeSection';
import { JournalTypeManager } from './JournalTypeManager';
import { ActivityFeed as JournalActivityFeed } from './ActivityFeed';
import { CreateAlbumButton } from './CreateAlbumButton';
import { InlineEditHeading } from './InlineEditHeading';
import { JournalContentInline } from './JournalContentInline';
import { InlineEditDateRange } from './InlineEditDateRange';
import { MergeJournalDialog } from './MergeJournalDialog';
import { ReviewSuggestions } from './ReviewSuggestions';
import { validateRequired } from '@/lib/validation';
import { StravaUnmatchedAthletesBadge } from '@/components/integrations/StravaUnmatchedAthletesBadge';
import { ExternalLinksDisplay } from '@/components/shared/ExternalLinksDisplay';
import { useJournalExternalLinks } from '@/lib/api/external-links';
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
  useUpdateContactRelationship,
  journalKeys,
} from '@/lib/api/journals';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';

interface JournalDetailViewProps {
  readonly journal: Journal;
  readonly className?: string;
}

/**
 * Journal types whose backend row has a required field with no default (e.g. a
 * mandatory gear_item_id) and therefore cannot be persisted by an empty "add".
 * These are added to a local pending list first so their inline editor renders;
 * the type is only created on the backend once the user saves the initial data.
 */
const TYPES_REQUIRING_INITIAL_DATA: ReadonlySet<JournalType> = new Set([
  JournalType.GEAR_USAGE,
]);

/** Union of type-specific data shapes a type editor can emit on save. */
type JournalTypeSaveData =
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
  | OutdoorPlanningData
  | OutdoorTrainingData
  | GearMaintenanceData
  | GearUsageData;

/**
 * Full journal detail view component.
 * Displays all journal information with inline editing capabilities.
 */
export function JournalDetailView({
  journal,
  className,
}: JournalDetailViewProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // Mutations
  const updateJournal = useUpdateJournal();
  const updateTypeData = useUpdateTypeData();
  const deleteJournal = useDeleteJournal();
  const addContact = useAddContactRelationship();
  const removeContact = useRemoveContactRelationship();
  const updateContact = useUpdateContactRelationship();
  const addTag = useAddJournalTag();
  const removeTag = useRemoveJournalTag();
  const addType = useAddJournalType();
  const removeType = useRemoveJournalType();

  // Types the user has added locally but not yet persisted because they require
  // initial data (see TYPES_REQUIRING_INITIAL_DATA). Their inline editor renders
  // so the user can supply the data; saving creates the type on the backend.
  const [pendingTypes, setPendingTypes] = useState<JournalType[]>([]);

  const persistedTypes = journal.types || [];
  const displayedTypes = [
    ...persistedTypes,
    ...pendingTypes.filter(type => !persistedTypes.includes(type)),
  ];

  // Data fetching
  const { data: tagsResponse } = useJournalTags();
  const { data: calendarsData } = useCalendars();
  const { data: externalLinksData } = useJournalExternalLinks(journal.id);

  const availableTags = tagsResponse?.data || [];
  const availableCalendars: JournalCalendar[] =
    calendarsData?.data.map(c => ({
      id: c.id,
      name: c.attributes.name,
      color: c.attributes.color,
    })) || [];

  let defaultStatus: AttendeeStatus | undefined;
  if (journal.event_date_range?.start) {
    defaultStatus = isPast(parseISO(journal.event_date_range.start))
      ? AttendeeStatus.ATTENDED
      : AttendeeStatus.ATTENDING;
  }

  // Handlers
  const handleCalendarChange = async (calendarId: string) => {
    await updateTypeData.mutateAsync({
      journalId: journal.id,
      journalType: JournalType.EVENT,
      typeData: {
        calendar_id: calendarId,
        is_all_day: false,
        sync_invitees: false,
        private_description: false,
      },
    });
  };

  const handleContactAdd = async (
    contactIds: string[],
    relationshipType: JournalContactRelationshipType,
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => {
    const results = await Promise.allSettled(
      contactIds.map(contactId =>
        addContact.mutateAsync({
          journalId: journal.id,
          contactId: contactId,
          relationshipType,
          status,
          role,
        })
      )
    );

    const failures = results.filter(
      (r): r is PromiseRejectedResult => r.status === 'rejected'
    );
    if (failures.length > 0) {
      const firstError =
        failures[0].reason instanceof Error
          ? failures[0].reason.message
          : String(failures[0].reason);
      throw new Error(
        `Failed to add ${failures.length} contact(s). First error: ${firstError}`
      );
    }
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

  const handleContactUpdate = async (
    contactId: string,
    relationshipType: JournalContactRelationshipType,
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => {
    await updateContact.mutateAsync({
      journalId: journal.id,
      contactId: contactId,
      relationshipType,
      status,
      role,
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
    if (TYPES_REQUIRING_INITIAL_DATA.has(type)) {
      // Defer backend creation until the user supplies the required initial
      // data via the inline editor (handlePendingTypeSave).
      setPendingTypes(prev => (prev.includes(type) ? prev : [...prev, type]));
      return;
    }

    await addType.mutateAsync({
      journalId: journal.id,
      journalType: type,
    });
  };

  const handleTypeRemove = async (type: JournalType) => {
    // Always drop any local pending entry for this type. This both handles the
    // still-pending case (nothing persisted to delete) and clears a stale
    // pending entry left over from a save, so the type can't resurface after
    // its persisted row is removed.
    const isStillPending =
      pendingTypes.includes(type) && !persistedTypes.includes(type);
    setPendingTypes(prev => prev.filter(t => t !== type));

    if (isStillPending) {
      return;
    }

    await removeType.mutateAsync({
      journalId: journal.id,
      journalType: type,
    });
  };

  // Save handler for pending types: creates the type on the backend with its
  // initial data. We deliberately do NOT remove the entry from pendingTypes
  // here: useAddJournalType only invalidates the detail query, so journal.types
  // won't carry the type until the async refetch lands. displayedTypes dedupes
  // a pending entry against persistedTypes, so once persisted the section keeps
  // rendering (from persisted data) with no flicker; keeping the stale pending
  // entry around is harmless and it is dropped on type removal.
  const handlePendingTypeSave = useCallback(
    async (type: JournalType, data: JournalTypeSaveData) => {
      await addType.mutateAsync({
        journalId: journal.id,
        journalType: type,
        typeData: data as Record<string, unknown>,
      });
    },
    [journal.id, addType]
  );

  // Handle type-specific data update
  const handleTypeDataSave = useCallback(
    async (type: JournalType, data: JournalTypeSaveData) => {
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

  // Handle template select for canyoning
  const handleTemplateSelect = useCallback(
    async (template: ActivityTemplateResource) => {
      if (
        template.attributes.pitches &&
        template.attributes.pitches.length > 0
      ) {
        const currentAbseil = journal.type_data?.[
          JournalType.ABSEILING_TRIP
        ] as AbseilingData | undefined;

        const pitches = template.attributes.pitches;
        const totalLength = pitches.reduce(
          (sum, p) => sum + (p.height || 0),
          0
        );

        await updateTypeData.mutateAsync({
          journalId: journal.id,
          journalType: JournalType.ABSEILING_TRIP,
          typeData: {
            ...(currentAbseil as Record<string, unknown>),
            pitches: pitches,
            number_of_abseils: pitches.length,
            total_length: totalLength,
          },
        });
        toast.success('Pitches imported from template');
      }
    },
    [journal.id, journal.type_data, updateTypeData]
  );

  // Handle adding an existing journal as a child of this journal
  const handleAddExistingChild = useCallback(
    async (childJournalId: string) => {
      await updateJournal.mutateAsync({
        id: childJournalId,
        data: {
          parent_id: Number(journal.id),
        },
      });
      // Re-parenting can affect both the new parent's and the previous parent's
      // children lists, so invalidate all journal detail queries.
      queryClient.invalidateQueries({
        queryKey: journalKeys.details(),
      });
    },
    [journal.id, updateJournal, queryClient]
  );

  // Handle changing the parent of this journal
  const handleParentChange = useCallback(
    async (parentId: string) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          parent_id: Number(parentId),
        },
      });
      // Re-parenting can affect both the new parent's and the previous parent's
      // children lists, so invalidate all journal detail queries.
      queryClient.invalidateQueries({
        queryKey: journalKeys.details(),
      });
    },
    [journal.id, updateJournal, queryClient]
  );

  // Handle removing the parent of this journal
  const handleParentRemove = useCallback(async () => {
    // Parent removal is intentionally disabled until the backend can
    // distinguish between an omitted `parent_id` field and an explicit
    // `parent_id: null` update. Sending `null` is currently treated as
    // "field not provided", and sending `0` would be validated as a real ID.
    return;
  }, []);

  return (
    <div
      className={cn('space-y-6', className)}
      data-testid='journal-detail-view'
    >
      {/* Breadcrumb Navigation */}
      <JournalBreadcrumb parent={journal.parent} currentTitle={journal.title} />

      {/* Review Suggestions */}
      {journal.review_items && journal.review_items.length > 0 && (
        <ReviewSuggestions
          journalId={journal.id}
          suggestions={journal.review_items}
        />
      )}

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
            <div className='flex items-center gap-2'>
              <CreateAlbumButton journal={journal} />
              <MergeJournalDialog targetJournalId={journal.id} />
              <Button
                variant='outline'
                size='sm'
                onClick={handleDelete}
                disabled={deleteJournal.isPending}
                aria-label='Delete journal'
                className='text-destructive hover:bg-destructive/10'
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
                currentTypes={displayedTypes}
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
                onRelationshipUpdate={handleContactUpdate}
                defaultStatus={defaultStatus}
              />
              <StravaUnmatchedAthletesBadge journalId={journal.id} />
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

            {/* External System Links */}
            <ExternalLinksDisplay
              links={externalLinksData?.data.map(d => d.attributes) ?? []}
            />

            {/* Parent Journal */}
            <div className='space-y-2'>
              <div className='text-sm font-medium'>Parent Journal</div>
              <JournalParentSelector
                currentJournalId={journal.id}
                parent={journal.parent}
                onParentChange={handleParentChange}
                onParentRemove={handleParentRemove}
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
          {displayedTypes.length > 0 && (
            <div className='space-y-4'>
              {displayedTypes.map(type => {
                const isPending =
                  pendingTypes.includes(type) && !persistedTypes.includes(type);
                return (
                  <JournalTypeSection
                    key={type}
                    journalId={journal.id}
                    type={type}
                    typeData={
                      isPending
                        ? undefined
                        : (journal.type_data?.[type] as JournalTypeData)
                    }
                    onSave={
                      isPending ? handlePendingTypeSave : handleTypeDataSave
                    }
                    onTemplateSelect={handleTemplateSelect}
                    defaultOpen={isPending}
                  />
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Children List - Always shown for add-child functionality */}
      <JournalChildrenList
        childJournals={journal.children ?? []}
        parentId={journal.id}
        onAddExisting={handleAddExistingChild}
      />

      {/* Activity History - field-level change history with provenance,
          rendered at the bottom of the detail screen (mirrors contacts).
          History is produced asynchronously, so entries may appear shortly
          after a change. */}
      <JournalActivityFeed journalId={journal.id} />
    </div>
  );
}
