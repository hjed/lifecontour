/**
 * ActivityItem component displays a single activity/history entry in the feed.
 *
 * Shows field changes with timestamp, action description, and visual indicators.
 */

'use client';

import { formatDistanceToNow } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { Edit, PlusCircle, Trash2 } from 'lucide-react';
import type { ContactHistoryResource } from '@/types/contacts';
import { cn } from '@/lib/utils';

interface ActivityItemProps {
  readonly activity: ContactHistoryResource;
  readonly className?: string;
}

/**
 * Format a field name for display (e.g., "first_name" -> "First Name").
 */
function formatFieldName(fieldName: string): string {
  return fieldName
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}

/**
 * Get activity type based on old and new values.
 */
function getActivityType(
  oldValue: string | null,
  newValue: string | null
): 'created' | 'updated' | 'deleted' {
  if (!oldValue && newValue) return 'created';
  if (oldValue && !newValue) return 'deleted';
  return 'updated';
}

/**
 * Get icon for activity type.
 */
function getActivityIcon(type: 'created' | 'updated' | 'deleted') {
  switch (type) {
    case 'created':
      return <PlusCircle className='h-4 w-4 text-green-500' />;
    case 'deleted':
      return <Trash2 className='h-4 w-4 text-red-500' />;
    case 'updated':
    default:
      return <Edit className='h-4 w-4 text-blue-500' />;
  }
}

/**
 * Format the activity description based on field and values.
 */
function formatActivityDescription(
  fieldName: string,
  oldValue: string | null,
  newValue: string | null,
  entityType: string
): string {
  const formattedField = formatFieldName(fieldName);
  const activityType = getActivityType(oldValue, newValue);

  // Format entity type for display
  const entityLabel = entityType.replace(/_/g, ' ').replace('contact ', '');

  switch (activityType) {
    case 'created':
      return `Added ${formattedField}: "${newValue}"`;
    case 'deleted':
      return `Removed ${formattedField}`;
    case 'updated':
      return `Changed ${formattedField} from "${oldValue}" to "${newValue}"`;
    default:
      return `Modified ${entityLabel}`;
  }
}

/**
 * Format timestamp for display.
 */
function formatTimestamp(timestamp: string | null): string {
  if (!timestamp) return 'Unknown time';

  try {
    const date = new Date(timestamp);
    return formatDistanceToNow(date, {
      addSuffix: true,
      locale: enAU,
    });
  } catch {
    return 'Unknown time';
  }
}

export function ActivityItem({ activity, className }: ActivityItemProps) {
  const { entity_type, field_name, old_value, new_value, created_at } =
    activity.attributes;
  const activityType = getActivityType(old_value, new_value);

  return (
    <div
      className={cn('flex items-start gap-3 py-2', className)}
      data-testid={`activity-item-${activity.id}`}
    >
      {/* Icon */}
      <div className='mt-0.5 flex-shrink-0'>
        {getActivityIcon(activityType)}
      </div>

      {/* Content */}
      <div className='min-w-0 flex-1'>
        <p className='text-sm'>
          {formatActivityDescription(
            field_name,
            old_value,
            new_value,
            entity_type
          )}
        </p>
        <p className='text-muted-foreground text-xs'>
          {formatTimestamp(created_at)}
        </p>
      </div>
    </div>
  );
}

// Export utility functions for testing
export { formatFieldName, getActivityType, formatActivityDescription };
