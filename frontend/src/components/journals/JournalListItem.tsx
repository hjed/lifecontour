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
  Activity,
  Mountain,
  Trees,
  Timer,
  ArrowDownToLine,
  Droplets,
  TrendingUp,
  Waves,
  Snowflake,
  Cloud,
  Ban,
  GitBranch,
} from 'lucide-react';
import { differenceInCalendarDays, parseISO } from 'date-fns';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { JournalType, EventState, CalendarInfoData } from '@/types/journals';
import { DisplayJournal } from '@/hooks/useDisplayJournals';
import { SearchHighlight } from '@/components/search/SearchHighlight';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { cn } from '@/lib/utils';
import { formatDateRange } from '@/lib/date-utils';
import { JournalChildrenList } from './JournalChildrenList';

interface JournalListItemProps {
  readonly journal: DisplayJournal;
  readonly focusDate?: string; // YYYY-MM-DD
  readonly className?: string;
}

// Icon mapping for journal types
const TYPE_ICONS: Record<
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
  [JournalType.CLIMBING]: TrendingUp,
  [JournalType.KAYAKING]: Waves,
  [JournalType.CROSS_COUNTRY_SKIING]: Snowflake,
};

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
export function JournalListItem({
  journal,
  focusDate,
  className,
}: JournalListItemProps) {
  const calendarColor = journal.calendar?.color || '#6b7280'; // Default gray

  const displayTitle = journal.highlightedTitle || journal.title;
  const displayContent =
    journal.highlightedContent || truncateContent(journal.content);

  const isCancelled =
    (journal.type_data?.event as CalendarInfoData | undefined)?.event_state ===
    EventState.CANCELLED;
  const isHierarchyNode =
    Boolean(journal.parent_id) || (journal.children_count ?? 0) > 0;

  // Calculate depth limit based on date proximity
  let shouldExpandChildren = true;
  if (journal.depth !== undefined && journal.depth !== null) {
    if (focusDate) {
      const distance = Math.abs(
        differenceInCalendarDays(
          parseISO(journal.event_date_range.start),
          parseISO(focusDate)
        )
      );
      const maxDepth = distance <= 7 ? 3 : 1;
      shouldExpandChildren = journal.depth < maxDepth;
    } else {
      shouldExpandChildren = journal.depth < 3; // Default 3 if no focus
    }
  }

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
              {journal.types.map(type => {
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
            {isHierarchyNode && (
              <GitBranch
                className='text-muted-foreground h-4 w-4'
                aria-label='Part of a hierarchy'
                data-testid='hierarchy-indicator'
              />
            )}
            {journal.calendar?.is_synced_to_google && (
              <Cloud
                className='text-muted-foreground h-4 w-4'
                aria-label='Synced to Google Calendar'
                data-testid='sync-indicator'
              />
            )}
            <Link
              href={`/journals/${journal.id}` as Route}
              className={cn(
                'hover:underline',
                isCancelled && 'text-muted-foreground line-through'
              )}
            >
              {journal.isSearchResult ? (
                <SearchHighlight text={displayTitle} fallback={journal.title} />
              ) : (
                journal.title
              )}
            </Link>
            {isCancelled && (
              <Badge
                variant='outline'
                className='text-muted-foreground border-muted-foreground ml-2 px-1 py-0 text-[10px] leading-none font-bold uppercase'
                data-testid='cancelled-badge'
              >
                <Ban className='mr-1 inline h-3 w-3' />
                Cancelled
              </Badge>
            )}
            {journal.has_pending_reviews && (
              <Badge
                variant='destructive'
                className='ml-2 px-1 py-0 text-[10px] leading-none font-bold uppercase'
                data-testid='needs-review-badge'
              >
                Needs Review
              </Badge>
            )}
          </CardTitle>
        </div>
      </CardHeader>

      <CardContent className='space-y-3 pl-5'>
        {/* Date display */}
        <div className='text-muted-foreground text-sm'>
          {formatDateRange(
            journal.event_date_range.start,
            journal.event_date_range.end
          )}
        </div>

        {/* Tags */}
        {journal.tags.length > 0 && (
          <div className='flex flex-wrap gap-1'>
            {journal.tags.map(tag => (
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
        {journal.contacts.length > 0 && (
          <div
            className='flex items-center gap-1'
            data-testid='journal-contacts-stack'
          >
            <div className='flex -space-x-2 overflow-hidden'>
              {journal.contacts.slice(0, 3).map(contact => {
                const fallbackDisplayName =
                  contact.name?.trim() || `Contact ${contact.id}`;
                const nameParts = fallbackDisplayName.split(/\s+/);
                const firstName = contact.first_name ?? nameParts[0] ?? '';
                const lastName =
                  contact.last_name ?? nameParts.slice(1).join(' ');

                return (
                  <Link
                    key={`${contact.id}-${contact.relationship_type}`}
                    href={`/contacts/${contact.id}` as Route}
                    aria-label={`View ${contact.name || `Contact ${contact.id}`}`}
                    className='ring-background focus-visible:ring-primary inline-block rounded-full ring-2 hover:z-10 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none'
                  >
                    <ContactAvatar
                      firstName={firstName}
                      lastName={lastName}
                      size='sm'
                    />
                  </Link>
                );
              })}
            </div>
            {journal.contacts.length > 3 && (
              <span
                className='text-muted-foreground ml-1 text-xs font-medium'
                data-testid='journal-contacts-overflow'
              >
                +{journal.contacts.length - 3}
              </span>
            )}
          </div>
        )}

        {/* Content excerpt */}
        {journal.content && (
          <p className='text-muted-foreground text-sm'>
            {journal.isSearchResult ? (
              <SearchHighlight
                text={displayContent}
                fallback={truncateContent(journal.content)}
              />
            ) : (
              truncateContent(journal.content)
            )}
          </p>
        )}

        {/* Children List */}
        {shouldExpandChildren &&
          journal.children &&
          journal.children.length > 0 && (
            <div className='pt-2'>
              <JournalChildrenList childJournals={journal.children} />
            </div>
          )}
      </CardContent>
    </Card>
  );
}
