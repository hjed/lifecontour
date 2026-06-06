import Link from 'next/link';
import { CardTitle } from '@/components/ui/card';
import { FavouriteToggle } from '@/components/contacts/FavouriteToggle';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { DisplayContact } from '@/hooks/useDisplayContacts';

interface ContactCardHeaderProps {
  readonly contact: DisplayContact;
}

export function ContactCardHeader({ contact }: ContactCardHeaderProps) {
  return (
    <div className='flex items-start justify-between gap-2'>
      <div className='flex items-center gap-3'>
        <ContactAvatar
          firstName={contact.first_name}
          lastName={contact.last_name}
          imageUrl={contact.photo_url ?? undefined}
          size='sm'
        />
        <CardTitle className='text-lg'>
          <Link href={`/contacts/${contact.id}`} className='hover:underline'>
            {contact.name}
          </Link>
        </CardTitle>
      </div>
      <FavouriteToggle
        contactId={contact.id}
        isFavourite={contact.is_favourite}
        contactName={contact.name}
      />
    </div>
  );
}
