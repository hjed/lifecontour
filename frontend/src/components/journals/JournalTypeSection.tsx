/**
 * JournalTypeSection component for displaying collapsible type-specific data sections.
 *
 * Provides a collapsible section for each journal type with inline editing capabilities.
 * Integrates with type-specific editor components for different journal types.
 */

'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { JournalType } from '@/types/journals';
import type {
  AbseilingData,
  BushwalkingData,
  CalendarInfoData,
  CanyoningData,
  ClimbingData,
  CrossCountrySkiingData,
  KayakingData,
  JoggingData,
  MoodData,
  OutdoorActivityData,
  PhotoAlbumData,
  PlanData,
  TravelData,
  FitnessData,
} from '@/types/journals';
import { cn } from '@/lib/utils';
import {
  EventTypeEditor,
  MoodRatingTypeEditor,
  PhotoAlbumTypeEditor,
  PlanTypeEditor,
  TravelTypeEditor,
  FitnessTypeEditor,
  OutdoorActivityTypeEditor,
  JoggingTypeEditor,
  BushwalkingTypeEditor,
} from './type-editors';

/** Union of all type-specific data shapes supported by JournalTypeSection. */
type TypeSectionData =
  | CalendarInfoData
  | MoodData
  | PhotoAlbumData
  | PlanData
  | TravelData
  | FitnessData
  | OutdoorActivityData
  | BushwalkingData
  | JoggingData
  | AbseilingData
  | CanyoningData
  | ClimbingData
  | KayakingData
  | CrossCountrySkiingData;

/** Callback invoked when the user saves type-specific data. */
type OnSaveFn = (type: JournalType, data: TypeSectionData) => Promise<void>;

interface JournalTypeSectionProps {
  readonly journalId: string;
  readonly type: JournalType;
  readonly typeData?: TypeSectionData;
  readonly onSave?: OnSaveFn;
  readonly defaultOpen?: boolean;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

// Display labels for journal types
const TYPE_SECTION_LABELS: Record<JournalType, string> = {
  [JournalType.NOTE]: 'Note Details',
  [JournalType.EVENT]: 'Event Details',
  [JournalType.MOOD_RATING]: 'Mood & Energy',
  [JournalType.PLAN]: 'Plan Documents',
  [JournalType.TRAVEL]: 'Travel Itinerary',
  [JournalType.PHOTO_ALBUM]: 'Photo Album',
  [JournalType.FITNESS]: 'Fitness Activity',
  [JournalType.OUTDOOR_ACTIVITY]: 'Outdoor Activity',
  [JournalType.BUSHWALKING]: 'Bushwalking',
  [JournalType.JOGGING]: 'Jogging',
  [JournalType.ABSEILING_TRIP]: 'Abseiling Trip',
  [JournalType.CANYONING]: 'Canyoning',
  [JournalType.CLIMBING]: 'Climbing',
  [JournalType.KAYAKING]: 'Kayaking',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
};

/**
 * JournalTypeSection component displays a collapsible section for type-specific data.
 *
 * @example
 * ```tsx
 * <JournalTypeSection
 *   journalId="123"
 *   type={JournalType.EVENT}
 *   typeData={eventData}
 * />
 * ```
 */
export function JournalTypeSection({
  journalId,
  type,
  typeData,
  onSave,
  defaultOpen = false,
  className,
  'data-testid': testId,
}: JournalTypeSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const sectionLabel = TYPE_SECTION_LABELS[type];

  return (
    <Card
      className={cn('overflow-hidden', className)}
      data-testid={testId || `type-section-${type}`}
    >
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CardHeader className='p-4'>
          <CollapsibleTrigger asChild>
            <Button
              variant='ghost'
              className='flex w-full items-center justify-between p-0 hover:bg-transparent'
              aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${sectionLabel}`}
              data-testid={`type-section-trigger-${type}`}
            >
              <CardTitle className='text-base font-semibold'>
                {sectionLabel}
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
          <CardContent className='px-4 pt-0 pb-4'>
            {/* Type-specific content will be rendered here */}
            <TypeSpecificContent
              journalId={journalId}
              type={type}
              typeData={typeData}
              onSave={onSave}
            />
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

/**
 * Creates a bound save handler for an editor component, or returns undefined when
 * no parent save callback is provided. Extracted to reduce cognitive complexity in
 * TypeSpecificContent's switch statement.
 */
function makeEditorSave<T extends TypeSectionData>(
  onSave: OnSaveFn | undefined,
  type: JournalType
): ((data: T) => Promise<void>) | undefined {
  if (!onSave) return undefined;
  return async (data: T) => onSave(type, data);
}

/**
 * TypeSpecificContent component renders the appropriate editor for each type.
 */
function TypeSpecificContent({
  journalId,
  type,
  typeData,
  onSave,
}: {
  readonly journalId: string;
  readonly type: JournalType;
  readonly typeData?: TypeSectionData;
  readonly onSave?: OnSaveFn;
}) {
  // Render type-specific editor based on journal type
  switch (type) {
    case JournalType.EVENT:
      return (
        <EventTypeEditor
          journalId={journalId}
          data={typeData as CalendarInfoData | undefined}
          onSave={makeEditorSave<CalendarInfoData>(onSave, type)}
        />
      );
    case JournalType.MOOD_RATING:
      return (
        <MoodRatingTypeEditor
          journalId={journalId}
          data={typeData as MoodData | undefined}
          onSave={makeEditorSave<MoodData>(onSave, type)}
        />
      );
    case JournalType.PHOTO_ALBUM:
      return (
        <PhotoAlbumTypeEditor
          journalId={journalId}
          data={typeData as PhotoAlbumData | undefined}
          onSave={makeEditorSave<PhotoAlbumData>(onSave, type)}
        />
      );
    case JournalType.PLAN:
      return (
        <PlanTypeEditor
          journalId={journalId}
          data={typeData as PlanData | undefined}
          onSave={makeEditorSave<PlanData>(onSave, type)}
        />
      );
    case JournalType.TRAVEL:
      return (
        <TravelTypeEditor
          journalId={journalId}
          data={typeData as TravelData | undefined}
          onSave={makeEditorSave<TravelData>(onSave, type)}
        />
      );
    case JournalType.FITNESS:
      return (
        <FitnessTypeEditor
          journalId={journalId}
          data={typeData as FitnessData | undefined}
          onSave={makeEditorSave<FitnessData>(onSave, type)}
        />
      );
    case JournalType.OUTDOOR_ACTIVITY:
      return (
        <OutdoorActivityTypeEditor
          journalId={journalId}
          data={typeData as OutdoorActivityData | undefined}
          onSave={makeEditorSave<OutdoorActivityData>(onSave, type)}
        />
      );
    case JournalType.JOGGING:
      return (
        <JoggingTypeEditor
          journalId={journalId}
          data={typeData as JoggingData | undefined}
          onSave={makeEditorSave<JoggingData>(onSave, type)}
        />
      );
    case JournalType.BUSHWALKING:
      return (
        <BushwalkingTypeEditor
          journalId={journalId}
          data={typeData as BushwalkingData | undefined}
          onSave={makeEditorSave<BushwalkingData>(onSave, type)}
        />
      );
    case JournalType.NOTE:
    default:
      // NOTE type doesn't have additional type-specific data
      return (
        <div
          className='text-muted-foreground text-sm'
          data-testid={`type-content-${type}`}
        >
          <p>No additional type-specific data for {type}.</p>
        </div>
      );
  }
}
