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
  CalendarInfoData,
  MoodData,
  PhotoAlbumData,
  PlanData,
  TravelData,
} from '@/types/journals';
import { cn } from '@/lib/utils';
import {
  EventTypeEditor,
  MoodRatingTypeEditor,
  PhotoAlbumTypeEditor,
  PlanTypeEditor,
  TravelTypeEditor,
} from './type-editors';

interface JournalTypeSectionProps {
  readonly journalId: string;
  readonly type: JournalType;
  readonly typeData?:
    | CalendarInfoData
    | MoodData
    | PhotoAlbumData
    | PlanData
    | TravelData;
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
            />
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

/**
 * TypeSpecificContent component renders the appropriate editor for each type.
 */
function TypeSpecificContent({
  journalId,
  type,
  typeData,
}: {
  journalId: string;
  type: JournalType;
  typeData?:
    | CalendarInfoData
    | MoodData
    | PhotoAlbumData
    | PlanData
    | TravelData;
}) {
  // Render type-specific editor based on journal type
  switch (type) {
    case JournalType.EVENT:
      return (
        <EventTypeEditor
          journalId={journalId}
          data={typeData as CalendarInfoData | undefined}
        />
      );
    case JournalType.MOOD_RATING:
      return (
        <MoodRatingTypeEditor
          journalId={journalId}
          data={typeData as MoodData | undefined}
        />
      );
    case JournalType.PHOTO_ALBUM:
      return (
        <PhotoAlbumTypeEditor
          journalId={journalId}
          data={typeData as PhotoAlbumData | undefined}
        />
      );
    case JournalType.PLAN:
      return (
        <PlanTypeEditor
          journalId={journalId}
          data={typeData as PlanData | undefined}
        />
      );
    case JournalType.TRAVEL:
      return (
        <TravelTypeEditor
          journalId={journalId}
          data={typeData as TravelData | undefined}
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
