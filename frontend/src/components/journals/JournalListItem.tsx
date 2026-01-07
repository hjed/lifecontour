/**
 * JournalListItem component for displaying individual journal cards in a list.
 *
 * Displays journal title, date, type icons, tags, contacts, and content excerpt
 * with calendar color bar on the left edge.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import {
  FileText,
  Calendar,
  Heart,
  ClipboardList,
  Plane,
  Image,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { JournalResource, JournalType } from '@/types/journals';
import { cn } from '@/lib/utils';
import { formatDateRange } from '@/lib/date-utils';

interface JournalListItemProps {
  readonly journal: JournalResource;
  readonly className?: string;
}

// Icon mapping for journal types
const TYPE_ICONS = {
  [JournalType.NOTE]: FileText,
  [JournalType.EVENT]: Calendar,
  [JournalType.MOOD_RATING]: Heart,
  [JournalType.PLAN]: ClipboardList,
  [JournalType.TRAVEL]: Plane,
  [JournalType.PHOTO_ALBUM]: Image,
} as const;

/**
 * Truncate content to specified length
 */
function truncateContent(content: string, maxLength: number = 200): string {
  if (content.length <= maxLength) return content;
  return content.substring(0, maxLength).trim() + '...';
}

/**
 * JournalListItem component displays a journal card with all relevant information
 */
export function JournalListItem({ journal, className }: JournalListItemProps) {
  const { attributes } = journal;
  const calendarColor = attributes.calendar?.color || '#6b7280'; // Default gray

  return (
    <Card
      key={journal.id}
      data-testid={`journal-${journal.id}`}
      className={cn(
        'relative overflow-hidden transition-shadow hover:shadow-md',
        className
      )}
    >
      {/* Calendar color bar on left edge */}
      <div
        className='absolute top-0 left-0 h-full w-1'
        style={{ backgroundColor: calendarColor }}
        aria-hidden='true'
      />

      <CardHeader className='pl-5'>
        <div className='flex items-start justify-between gap-2'>
          <CardTitle className='flex items-center gap-2 text-lg'>
            {/* Type icons */}
            <div className='flex gap-1' aria-label='Journal types'>
              {attributes.types.map(type => {
                const Icon = TYPE_ICONS[type];
                return Icon ? (
                  <Icon
                    key={type}
                    className='text-muted-foreground h-4 w-4'
                    aria-label={type}
                  />
                ) : null;
              })}
            </div>
            <Link
              href={`/journals/${journal.id}` as Route}
              className='hover:underline'
            >
              {attributes.title}
            </Link>
          </CardTitle>
        </div>
      </CardHeader>

      <CardContent className='space-y-3 pl-5'>
        {/* Date display */}
        <div className='text-muted-foreground text-sm'>
          {formatDateRange(
            attributes.event_date_range.start,
            attributes.event_date_range.end
          )}
        </div>

        {/* Tags */}
        {attributes.tags.length > 0 && (
          <div className='flex flex-wrap gap-1'>
            {attributes.tags.map(tag => (
              <Badge
                key={tag.id}
                variant='secondary'
                className='text-xs'
                style={tag.color ? { backgroundColor: tag.color } : undefined}
                data-testid={`tag-${tag.name}`}
              >
                {tag.name}
              </Badge>
            ))}
          </div>
        )}

        {/* Contact chips */}
        {attributes.contacts.length > 0 && (
          <div className='flex flex-wrap gap-2'>
            {attributes.contacts.map(contact => (
              <div
                key={`${contact.id}-${contact.relationshipType}`}
                className='bg-muted text-muted-foreground flex items-center gap-1 rounded-full px-2 py-1 text-xs'
                data-testid={`contact-${contact.id}`}
              >
                <span>👤</span>
                <span>{contact.name || `Contact ${contact.id}`}</span>
              </div>
            ))}
          </div>
        )}

        {/* Content excerpt */}
        {attributes.content && (
          <p className='text-muted-foreground text-sm'>
            {truncateContent(attributes.content)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
