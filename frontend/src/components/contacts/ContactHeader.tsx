import { ContactAvatar } from './ContactAvatar';
import { FavouriteToggle } from './FavouriteToggle';
import { Badge } from '@/components/ui/badge';
import { cn, generateDisplayName } from '@/lib/utils';
import { TagResource } from '@/types/contacts';

/**
 * @deprecated ContactHeader is deprecated. Use page-level CSS Grid layout with ContactAvatar and ContactIdentity components instead.
 *
 * This component was designed for flexbox layout but the new design uses CSS Grid with:
 * - ContactAvatar in the first column
 * - ContactIdentity in the second column
 * - Activity/relationships sidebar in the third column
 *
 * See the contact detail page (/app/contacts/[id]/page.tsx) for the new implementation.
 */
interface ContactHeaderProps {
  readonly contact: {
    readonly id: string;
    readonly firstName: string;
    readonly lastName?: string;
    readonly nickName?: string;
    readonly isFavourite: boolean;
    readonly tags?: TagResource[];
  };
  readonly avatarSize?: 'sm' | 'md' | 'lg';
  readonly className?: string;
}

/**
 * ContactHeader component displays contact name, avatar, tags, and favourite toggle.
 *
 * @deprecated ContactHeader is deprecated. Use page-level CSS Grid layout with ContactAvatar and ContactIdentity components instead.
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
  const displayName = generateDisplayName(
    contact.firstName,
    contact.lastName || ''
  );

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
