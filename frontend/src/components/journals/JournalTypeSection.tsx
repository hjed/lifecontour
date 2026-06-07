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
import { ActivityTemplateResource, JournalType } from '@/types/journals';
import type {
  AbseilingData,
  BushwalkingData,
  CalendarInfoData,
  CanoeingData,
  CanyoningData,
  CavingData,
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
  OutdoorPlanningData,
  OutdoorTrainingData,
  GearMaintenanceData,
  GearUsageData,
} from '@/types/journals';
import { cn } from '@/lib/utils';
import {
  AbseilingTripTypeEditor,
  BushwalkingTypeEditor,
  CanoeingTypeEditor,
  CanyoningTypeEditor,
  CavingTypeEditor,
  ClimbingTypeEditor,
  CrossCountrySkiingTypeEditor,
  EventTypeEditor,
  FitnessTypeEditor,
  JoggingTypeEditor,
  KayakingTypeEditor,
  MoodRatingTypeEditor,
  OutdoorActivityTypeEditor,
  PlanTypeEditor,
  TravelTypeEditor,
  SnorkellingTypeEditor,
  DivingTypeEditor,
  DownhillSkiingTypeEditor,
  OutdoorPlanningTypeEditor,
  OutdoorTrainingTypeEditor,
  GearMaintenanceTypeEditor,
  GearUsageTypeEditor,
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
  | CavingData
  | CanoeingData
  | ClimbingData
  | KayakingData
  | CrossCountrySkiingData
  | OutdoorPlanningData
  | OutdoorTrainingData
  | GearMaintenanceData;

/** Callback invoked when the user saves type-specific data. */
type OnSaveFn = (type: JournalType, data: TypeSectionData) => Promise<void>;

interface JournalTypeSectionProps {
  readonly journalId: string;
  readonly type: JournalType;
  readonly typeData?: TypeSectionData;
  readonly onSave?: OnSaveFn;
  readonly onTemplateSelect?: (template: ActivityTemplateResource) => void;
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
  [JournalType.CAVING]: 'Caving',
  [JournalType.CANOEING]: 'Canoeing',
  [JournalType.CLIMBING]: 'Climbing Data',
  [JournalType.KAYAKING]: 'Kayaking Data',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
  [JournalType.SNORKELLING]: 'Snorkelling',
  [JournalType.DIVING]: 'Diving',
  [JournalType.DOWNHILL_SKIING]: 'Downhill Skiing',
  [JournalType.OUTDOOR_PLANNING]: 'Outdoor Planning',
  [JournalType.OUTDOOR_TRAINING]: 'Outdoor Training',
  [JournalType.GEAR_MAINTENANCE]: 'Gear Maintenance',
  [JournalType.GEAR_USAGE]: 'Gear Usage',
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
  onTemplateSelect,
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
              onTemplateSelect={onTemplateSelect}
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
  onTemplateSelect,
}: {
  readonly journalId: string;
  readonly type: JournalType;
  readonly typeData?: TypeSectionData;
  readonly onSave?: OnSaveFn;
  readonly onTemplateSelect?: (template: ActivityTemplateResource) => void;
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
    case JournalType.PHOTO_ALBUM: {
      // PHOTO_ALBUM is managed by Immich album sync and is read-only here.
      const album = typeData as PhotoAlbumData | undefined;
      return (
        <div
          className='text-muted-foreground text-sm'
          data-testid='photo-album-readonly'
        >
          {(album?.album_name ?? album?.immich_album_id)
            ? `Synced from Immich album: ${album?.album_name ?? album?.immich_album_id}`
            : 'Synced from Immich. Album details are managed by Immich.'}
        </div>
      );
    }
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
    case JournalType.ABSEILING_TRIP:
      return (
        <AbseilingTripTypeEditor
          journalId={journalId}
          data={typeData as AbseilingData | undefined}
          onSave={makeEditorSave<AbseilingData>(onSave, type)}
        />
      );
    case JournalType.CANYONING:
      return (
        <CanyoningTypeEditor
          journalId={journalId}
          data={typeData as CanyoningData | undefined}
          onSave={makeEditorSave<CanyoningData>(onSave, type)}
          onTemplateSelect={onTemplateSelect}
        />
      );
    case JournalType.CAVING:
      return (
        <CavingTypeEditor
          journalId={journalId}
          data={typeData as CavingData | undefined}
          onSave={makeEditorSave<CavingData>(onSave, type)}
          onTemplateSelect={onTemplateSelect}
        />
      );
    case JournalType.CANOEING:
      return (
        <CanoeingTypeEditor
          journalId={journalId}
          data={typeData as CanoeingData | undefined}
          onSave={makeEditorSave<CanoeingData>(onSave, type)}
        />
      );
    case JournalType.CLIMBING:
      return (
        <ClimbingTypeEditor
          journalId={journalId}
          data={typeData as ClimbingData | undefined}
          onSave={makeEditorSave<ClimbingData>(onSave, type)}
          onTemplateSelect={onTemplateSelect}
        />
      );
    case JournalType.KAYAKING:
      return (
        <KayakingTypeEditor
          journalId={journalId}
          data={typeData as KayakingData | undefined}
          onSave={makeEditorSave<KayakingData>(onSave, type)}
        />
      );
    case JournalType.CROSS_COUNTRY_SKIING:
      return (
        <CrossCountrySkiingTypeEditor
          journalId={journalId}
          data={typeData as CrossCountrySkiingData | undefined}
          onSave={makeEditorSave<CrossCountrySkiingData>(onSave, type)}
        />
      );
    case JournalType.SNORKELLING:
      return (
        <SnorkellingTypeEditor
          journalId={journalId}
          data={typeData as Record<string, never> | undefined}
          onSave={makeEditorSave<Record<string, never>>(onSave, type)}
        />
      );
    case JournalType.DIVING:
      return (
        <DivingTypeEditor
          journalId={journalId}
          data={typeData as Record<string, never> | undefined}
          onSave={makeEditorSave<Record<string, never>>(onSave, type)}
        />
      );
    case JournalType.DOWNHILL_SKIING:
      return (
        <DownhillSkiingTypeEditor
          journalId={journalId}
          data={typeData as Record<string, never> | undefined}
          onSave={makeEditorSave<Record<string, never>>(onSave, type)}
        />
      );
    case JournalType.OUTDOOR_PLANNING:
      return (
        <OutdoorPlanningTypeEditor
          journalId={journalId}
          data={typeData as OutdoorPlanningData | undefined}
          onSave={makeEditorSave<OutdoorPlanningData>(onSave, type)}
        />
      );
    case JournalType.OUTDOOR_TRAINING:
      return (
        <OutdoorTrainingTypeEditor
          journalId={journalId}
          data={typeData as OutdoorTrainingData | undefined}
          onSave={makeEditorSave<OutdoorTrainingData>(onSave, type)}
        />
      );
    case JournalType.GEAR_MAINTENANCE:
      return (
        <GearMaintenanceTypeEditor
          journalId={journalId}
          data={typeData as GearMaintenanceData | undefined}
          onSave={makeEditorSave<GearMaintenanceData>(onSave, type)}
        />
      );
    case JournalType.GEAR_USAGE:
      return (
        <GearUsageTypeEditor
          journalId={journalId}
          data={typeData as GearUsageData | undefined}
          onSave={makeEditorSave<GearUsageData>(onSave, type)}
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
