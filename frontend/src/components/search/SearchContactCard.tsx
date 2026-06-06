import { Mail, Phone, Star, BookOpen, Activity, Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ContactCardHeader as SharedContactCardHeader } from '@/components/contacts/ContactCardHeader';
import { DisplayContact } from '@/hooks/useDisplayContacts';
import { ContactRankingSignals } from '@/utils/searchUtils';

interface SearchContactCardProps {
  readonly contact: DisplayContact;
  readonly signals: ContactRankingSignals;
}

/**
 * Search-specific contact card that displays ranking signal badges.
 *
 * Renders contact info alongside visual indicators for favourite status,
 * journal mentions, recent activity, and AI summary availability.
 */
export function SearchContactCard({
  contact,
  signals,
}: SearchContactCardProps) {
  return (
    <Card
      data-testid={`search-contact-${contact.id}`}
      className='transition-shadow hover:shadow-md'
    >
      <CardHeader className='pb-2'>
        <SharedContactCardHeader contact={contact} />

        {/* Ranking Signal Badges */}
        <div className='flex flex-wrap items-center gap-1.5 pt-1'>
          {signals.isFavourite && (
            <Badge
              variant='secondary'
              className='gap-1 bg-yellow-100 text-xs text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
              aria-label='Favourite contact'
            >
              <Star className='h-3 w-3 fill-current' aria-hidden='true' />
              Favourite
            </Badge>
          )}

          {signals.journalCount30d > 0 && (
            <Badge
              variant='secondary'
              className='gap-1 text-xs'
              aria-label={`${signals.journalCount30d} journal entries in last 30 days`}
            >
              <BookOpen className='h-3 w-3' aria-hidden='true' />
              {signals.journalCount30d}
            </Badge>
          )}

          {signals.activityCount30d > 0 && (
            <Badge
              variant='secondary'
              className='gap-1 text-xs'
              aria-label={`${signals.activityCount30d} recent activities`}
            >
              <Activity className='h-3 w-3' aria-hidden='true' />
              {signals.activityCount30d}
            </Badge>
          )}

          {signals.hasSummary && (
            <Badge
              variant='secondary'
              className='gap-1 bg-purple-100 text-xs text-purple-800 dark:bg-purple-900/30 dark:text-purple-300'
              aria-label='AI summary available'
            >
              <Sparkles className='h-3 w-3' aria-hidden='true' />
              Summary
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className='space-y-2 pt-0'>
        {/* Contact Methods */}
        <div className='space-y-1'>
          {contact.primary_email && (
            <div className='text-muted-foreground flex items-center gap-2 text-sm'>
              <Mail className='h-3.5 w-3.5' aria-hidden='true' />
              <span className='truncate'>{contact.primary_email}</span>
            </div>
          )}
          {contact.primary_phone && (
            <div className='text-muted-foreground flex items-center gap-2 text-sm'>
              <Phone className='h-3.5 w-3.5' aria-hidden='true' />
              <span>{contact.primary_phone}</span>
            </div>
          )}
        </div>

        {/* Tags */}
        {contact.tags.length > 0 && (
          <div className='flex flex-wrap gap-1'>
            {contact.tags.map(tag => (
              <Badge key={tag.id} variant='outline' className='text-xs'>
                {tag.attributes.name}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
