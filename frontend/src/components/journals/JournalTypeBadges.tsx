/**
 * JournalTypeBadges component for displaying journal types as visual badges.
 *
 * Displays journal types with appropriate icons and consistent styling.
 * Supports all journal types: NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL,
 * PHOTO_ALBUM, FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING,
 * ABSEILING_TRIP, CANYONING, CAVING, CANOEING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING.
 */

'use client';

import {
  FileText,
  Calendar,
  Heart,
  ClipboardList,
  Plane,
  Image,
  Activity,
  Mountain,
  Trees,
  Timer,
  ArrowDownToLine,
  Droplets,
  TrendingUp,
  Waves,
  Ship,
  Snowflake,
  MapPin,
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
export const TYPE_ICONS: Record<
  JournalType,
  React.ComponentType<{ className?: string }>
> = {
  [JournalType.NOTE]: FileText,
  [JournalType.EVENT]: Calendar,
  [JournalType.MOOD_RATING]: Heart,
  [JournalType.PLAN]: ClipboardList,
  [JournalType.TRAVEL]: Plane,
  [JournalType.PHOTO_ALBUM]: Image,
  [JournalType.FITNESS]: Activity,
  [JournalType.OUTDOOR_ACTIVITY]: Mountain,
  [JournalType.BUSHWALKING]: Trees,
  [JournalType.JOGGING]: Timer,
  [JournalType.ABSEILING_TRIP]: ArrowDownToLine,
  [JournalType.CANYONING]: Droplets,
  [JournalType.CAVING]: Mountain,
  [JournalType.CANOEING]: Ship,
  [JournalType.CLIMBING]: TrendingUp,
  [JournalType.KAYAKING]: Waves,
  [JournalType.CROSS_COUNTRY_SKIING]: Snowflake,
  [JournalType.SNORKELLING]: Waves,
  [JournalType.DIVING]: ArrowDownToLine,
  [JournalType.DOWNHILL_SKIING]: Snowflake,
  [JournalType.OUTDOOR_PLANNING]: MapPin,
};

// Display labels for journal types
export const TYPE_LABELS: Record<JournalType, string> = {
  [JournalType.NOTE]: 'Note',
  [JournalType.EVENT]: 'Event',
  [JournalType.MOOD_RATING]: 'Mood Rating',
  [JournalType.PLAN]: 'Plan',
  [JournalType.TRAVEL]: 'Travel',
  [JournalType.PHOTO_ALBUM]: 'Photo Album',
  [JournalType.FITNESS]: 'Fitness',
  [JournalType.OUTDOOR_ACTIVITY]: 'Outdoor Activity',
  [JournalType.BUSHWALKING]: 'Bushwalking',
  [JournalType.JOGGING]: 'Jogging',
  [JournalType.ABSEILING_TRIP]: 'Abseiling Trip',
  [JournalType.CANYONING]: 'Canyoning',
  [JournalType.CAVING]: 'Caving',
  [JournalType.CANOEING]: 'Canoeing',
  [JournalType.CLIMBING]: 'Climbing',
  [JournalType.KAYAKING]: 'Kayaking',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
  [JournalType.SNORKELLING]: 'Snorkelling',
  [JournalType.DIVING]: 'Diving',
  [JournalType.DOWNHILL_SKIING]: 'Downhill Skiing',
  [JournalType.OUTDOOR_PLANNING]: 'Outdoor Planning',
};

// Color variants for different journal types
export const TYPE_VARIANTS: Record<
  JournalType,
  'default' | 'secondary' | 'outline'
> = {
  [JournalType.NOTE]: 'secondary',
  [JournalType.EVENT]: 'default',
  [JournalType.MOOD_RATING]: 'outline',
  [JournalType.PLAN]: 'secondary',
  [JournalType.TRAVEL]: 'default',
  [JournalType.PHOTO_ALBUM]: 'outline',
  [JournalType.FITNESS]: 'default',
  [JournalType.OUTDOOR_ACTIVITY]: 'default',
  [JournalType.BUSHWALKING]: 'secondary',
  [JournalType.JOGGING]: 'secondary',
  [JournalType.ABSEILING_TRIP]: 'default',
  [JournalType.CANYONING]: 'default',
  [JournalType.CAVING]: 'default',
  [JournalType.CANOEING]: 'secondary',
  [JournalType.CLIMBING]: 'default',
  [JournalType.KAYAKING]: 'default',
  [JournalType.CROSS_COUNTRY_SKIING]: 'default',
  [JournalType.SNORKELLING]: 'default',
  [JournalType.DIVING]: 'default',
  [JournalType.DOWNHILL_SKIING]: 'default',
  [JournalType.OUTDOOR_PLANNING]: 'secondary',
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
      data-testid={testId ?? 'journal-type-badges'}
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
