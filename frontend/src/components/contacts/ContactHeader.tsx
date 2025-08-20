import { ContactAvatar } from './ContactAvatar';
import { FavouriteToggle } from './FavouriteToggle';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { TagResource } from '@/types/contacts';

interface ContactHeaderProps {
  contact: {
    id: string;
    firstName: string;
    lastName?: string;
    nickName?: string;
    isFavourite: boolean;
    tags?: TagResource[];
  };
  avatarSize?: 'sm' | 'md' | 'lg';
  className?: string;
}

/**
 * ContactHeader component displays contact name, avatar, tags, and favourite toggle.
 *
 * Features:
 * - Large avatar with initials fallback
 * - Contact name with nickname display
 * - Tags as badges
 * - Favourite toggle integration
 * - Responsive layout
 * - Full accessibility support
 */
export function ContactHeader({
  contact,
  avatarSize = 'lg',
  className,
}: ContactHeaderProps) {
  // Generate display name
  const generateDisplayName = (
    firstName: string,
    lastName?: string
  ): string => {
    const cleanFirst = firstName?.trim() || '';
    const cleanLast = lastName?.trim() || '';

    if (cleanFirst && cleanLast) {
      return `${cleanFirst} ${cleanLast}`;
    }

    return cleanFirst || cleanLast || '';
  };

  const displayName = generateDisplayName(contact.firstName, contact.lastName);

  return (
    <header
      className={cn('mb-6 flex items-center gap-4', className)}
      role='banner'
    >
      {/* Avatar */}
      <ContactAvatar
        firstName={contact.firstName}
        lastName={contact.lastName}
        size={avatarSize}
        className='mr-4'
      />

      {/* Contact Info */}
      <div className='min-w-0 flex-1'>
        {/* Name and Nickname */}
        <div className='mb-2 flex items-center gap-3'>
          <h1 className='text-2xl font-bold tracking-tight'>{displayName}</h1>
          {contact.nickName && contact.nickName.trim() && (
            <span className='text-muted-foreground text-lg font-medium'>
              &ldquo;{contact.nickName}&rdquo;
            </span>
          )}
          <FavouriteToggle
            contactId={contact.id}
            isFavourite={contact.isFavourite}
            contactName={displayName}
            size='md'
          />
        </div>

        {/* Tags */}
        {contact.tags && contact.tags.length > 0 && (
          <div className='flex flex-wrap gap-2'>
            {contact.tags.map(tag => (
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
    </header>
  );
}
