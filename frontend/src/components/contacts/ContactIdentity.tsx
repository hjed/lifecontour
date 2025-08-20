import { Badge } from '@/components/ui/badge';
import { generateDisplayName } from '@/lib/utils';
import { FavouriteToggle } from './FavouriteToggle';
import type { ContactResource, TagResource } from '@/types/contacts';

interface ContactIdentityProps {
  contact: ContactResource;
  className?: string;
}

/**
 * ContactIdentity component displays the contact's name, nickname, tags, and favourite toggle.
 * This component is designed to be used within a layout structure (e.g., CSS Grid column).
 */
export function ContactIdentity({ contact, className }: ContactIdentityProps) {
  const displayName = generateDisplayName(
    contact.attributes.first_name,
    contact.attributes.last_name || ''
  );

  const favouriteProps = {
    contactId: contact.id,
    contactName: displayName,
    isFavourite: contact.attributes.is_favourite || false,
  };

  return (
    <div className={className}>
      <div className='mb-2 flex items-center gap-3'>
        <h1 className='text-2xl font-bold tracking-tight'>{displayName}</h1>
        {contact.attributes.nick_name &&
          contact.attributes.nick_name.trim() && (
            <span className='text-muted-foreground text-lg font-medium'>
              &ldquo;{contact.attributes.nick_name}&rdquo;
            </span>
          )}
        <FavouriteToggle {...favouriteProps} />
      </div>

      {contact.relationships?.tags?.data &&
        contact.relationships.tags.data.length > 0 && (
          <div className='flex flex-wrap gap-2'>
            {contact.relationships.tags.data.map((tag: TagResource) => (
              <Badge
                key={tag.id}
                variant='secondary'
                className='text-xs'
                data-testid={`tag-${tag.attributes.name}`}
              >
                {tag.attributes.name}
              </Badge>
            ))}
          </div>
        )}
    </div>
  );
}
