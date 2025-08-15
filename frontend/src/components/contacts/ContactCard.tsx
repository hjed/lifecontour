import Link from 'next/link';
import { Mail, Phone, Calendar } from 'lucide-react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { FavouriteToggle } from '@/components/contacts/FavouriteToggle';
import { DisplayContact } from '@/hooks/useDisplayContacts';
import { DATE_FORMATS } from '@/lib/constants';

interface ContactCardProps {
  readonly contact: DisplayContact;
}

/**
 * Reusable contact card component
 * Eliminates duplicate contact card rendering logic across pages
 */
export function ContactCard({ contact }: ContactCardProps) {
  return (
    <Card
      key={contact.id}
      data-testid={`contact-${contact.id}`}
      className='transition-shadow hover:shadow-md'
    >
      <CardHeader>
        <div className='flex items-start justify-between'>
          <CardTitle className='text-lg'>
            <Link href={`/contacts/${contact.id}`} className='hover:underline'>
              {contact.name}
            </Link>
          </CardTitle>
          <FavouriteToggle
            contactId={contact.id}
            isFavourite={contact.is_favourite}
            contactName={contact.name}
          />
        </div>
      </CardHeader>
      <CardContent className='space-y-3'>
        {/* Contact Methods */}
        <div className='space-y-2'>
          {contact.primary_email && (
            <div className='text-muted-foreground flex items-center gap-2 text-sm'>
              <Mail className='h-4 w-4' aria-hidden='true' />
              <span>{contact.primary_email}</span>
            </div>
          )}
          {contact.primary_phone && (
            <div className='text-muted-foreground flex items-center gap-2 text-sm'>
              <Phone className='h-4 w-4' aria-hidden='true' />
              <span>{contact.primary_phone}</span>
            </div>
          )}
        </div>

        {/* Tags */}
        {contact.tags.length > 0 && (
          <div className='flex flex-wrap gap-1'>
            {contact.tags.map(tag => {
              const tagName = tag.attributes?.name || `Tag ${tag.id}`;
              const testId = `tag-${tagName}`;
              return (
                <Badge
                  key={tag.id}
                  variant='secondary'
                  className='text-xs'
                  data-testid={testId}
                >
                  {tagName}
                </Badge>
              );
            })}
          </div>
        )}

        {/* Created Date */}
        <div className='text-muted-foreground flex items-center gap-2 text-xs'>
          <Calendar className='h-3 w-3' aria-hidden='true' />
          <span>
            Added{' '}
            {format(new Date(contact.created_at), DATE_FORMATS.SHORT, {
              locale: enAU,
            })}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
