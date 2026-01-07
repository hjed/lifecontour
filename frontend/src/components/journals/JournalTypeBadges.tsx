/**
 * JournalTypeBadges component for displaying journal types as visual badges.
 *
 * Displays journal types with appropriate icons and consistent styling.
 * Supports all base journal types: NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM.
 */

'use client';

import {
  FileText,
  Calendar,
  Heart,
  ClipboardList,
  Plane,
  Image,
  Dumbbell,
  Mountain,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { JournalType } from '@/types/journals';
import { cn } from '@/lib/utils';

interface JournalTypeBadgesProps {
  readonly types: JournalType[];
  readonly className?: string;
  readonly 'data-testid'?: string;
}

// Icon mapping for journal types
const TYPE_ICONS = {
  [JournalType.NOTE]: FileText,
  [JournalType.EVENT]: Calendar,
  [JournalType.MOOD_RATING]: Heart,
  [JournalType.PLAN]: ClipboardList,
  [JournalType.TRAVEL]: Plane,
  [JournalType.PHOTO_ALBUM]: Image,
  // Future types (not yet in enum but prepared for expansion)
  FITNESS: Dumbbell,
  OUTDOOR_ACTIVITY: Mountain,
} as const;

// Display labels for journal types
const TYPE_LABELS: Record<JournalType, string> = {
  [JournalType.NOTE]: 'Note',
  [JournalType.EVENT]: 'Event',
  [JournalType.MOOD_RATING]: 'Mood Rating',
  [JournalType.PLAN]: 'Plan',
  [JournalType.TRAVEL]: 'Travel',
  [JournalType.PHOTO_ALBUM]: 'Photo Album',
};

// Color variants for different journal types
const TYPE_VARIANTS: Record<JournalType, 'default' | 'secondary' | 'outline'> =
  {
    [JournalType.NOTE]: 'secondary',
    [JournalType.EVENT]: 'default',
    [JournalType.MOOD_RATING]: 'outline',
    [JournalType.PLAN]: 'secondary',
    [JournalType.TRAVEL]: 'default',
    [JournalType.PHOTO_ALBUM]: 'outline',
  };

/**
 * JournalTypeBadges component displays journal types as visual badges with icons.
 *
 * @example
 * ```tsx
 * <JournalTypeBadges types={[JournalType.EVENT, JournalType.MOOD_RATING]} />
 * ```
 */
export function JournalTypeBadges({
  types,
  className,
  'data-testid': testId,
}: JournalTypeBadgesProps) {
  if (!types || types.length === 0) {
    return null;
  }

  return (
    <div
      className={cn('flex flex-wrap gap-2', className)}
      data-testid={testId || 'journal-type-badges'}
      aria-label='Journal types'
    >
      {types.map(type => {
        const Icon = TYPE_ICONS[type];
        const label = TYPE_LABELS[type];
        const variant = TYPE_VARIANTS[type];

        return (
          <Badge
            key={type}
            variant={variant}
            className='flex items-center gap-1.5'
            data-testid={`type-badge-${type}`}
          >
            {Icon && <Icon className='h-3.5 w-3.5' aria-hidden='true' />}
            <span>{label}</span>
          </Badge>
        );
      })}
    </div>
  );
}
